#!/usr/bin/env python3
"""
VOICE → OLLAMA → PIPER with Motor Tool Calling + Robust JSON-string parsing + motor-dir import fixes.

Run:
 ./venv/bin/python tool.py <piper_model> <piper_config> --vosk <vosk_model_dir> [--model <ollama_model>] [--chat-url <chat_url>] [--motor-dir <path>]
"""

import os
import sys
import json
import time
import argparse
import subprocess
import traceback
import shutil
import re
import pprint

from vosk import Model, KaldiRecognizer
import pyaudio

DEFAULT_OLLAMA_URL = "http://localhost:11434/api/generate"
DEFAULT_CHAT_URL = "http://localhost:11434/api/chat"
DEFAULT_MODEL_NAME = "qwen3:0.6b"
OUT_WAV = "speech_reply.wav"

STREAM_DEBUG = True
LOG_TOOL_DEBUG = True

# ---------- Text cleaning utilities ----------
EMOJI_PATTERN = re.compile(
    "[" 
    "\U0001F600-\U0001F64F"
    "\U0001F300-\U0001F5FF"
    "\U0001F680-\U0001F6FF"
    "\U0001F1E0-\U0001F1FF"
    "\U00002500-\U00002BEF"
    "\U00002700-\U000027BF"
    "\U0000FE00-\U0000FE0F"
    "\U000024C2-\U0001F251"
    "]+",
    flags=re.UNICODE,
)
_KEEP_PATTERN = re.compile(r"[^0-9A-Za-z\s\.\,\?\!\:\;\'\"\-\(\)]+")

def clean_for_tts(text: str) -> str:
    if not text:
        return ""
    text = text.replace("*", "")
    text = EMOJI_PATTERN.sub("", text)
    text = _KEEP_PATTERN.sub("", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text

def clean_received_text(text: str) -> str:
    if not text:
        return ""
    text = text.replace("*", "")
    text = re.sub(r"\s+", " ", text).strip()
    return text

# ------------------- Piper Wrapper -------------------
class PiperWrapper:
    def __init__(self, model_path, config_path):
        print("[PIPER] Loading Piper...")
        from piper_onnx import Piper
        self.p = Piper(model_path, config_path)
        print("[PIPER] Loaded successfully.")

    def synth(self, text, out_path=OUT_WAV):
        print("[PIPER] Synthesizing voice...")
        audio, sr = self.p.create(text)
        import numpy as np, wave
        pcm = (audio * 32767).astype("int16")
        with wave.open(out_path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sr)
            wf.writeframes(pcm.tobytes())
        print("[PIPER] Saved to", out_path)
        return out_path

# ------------------- Playback -------------------
def try_playback(wav):
    print("[PLAYBACK] Playing audio:", wav)
    aplay = shutil.which("aplay")
    if aplay:
        try:
            subprocess.run([aplay, wav], check=True)
            return
        except Exception as e:
            print("[PLAYBACK] aplay failed!", e)
    print("[PLAYBACK] Trying sounddevice...")
    try:
        import soundfile as sf, sounddevice as sd
        data, sr = sf.read(wav, dtype='int16')
        sd.play(data, sr)
        sd.wait()
    except Exception as e:
        print("[PLAYBACK] FAILED:", e)

# ------------------- VOSK Microphone -------------------
class VoiceListener:
    def __init__(self, model_path="model"):
        print("[VOSK] Loading model:", model_path)
        if not os.path.exists(model_path):
            raise RuntimeError("Vosk model folder not found!")
        self.model = Model(model_path)
        self.recognizer = KaldiRecognizer(self.model, 16000)
        self.p = pyaudio.PyAudio()
        print("[VOSK] Opening microphone...")
        self.stream = self.p.open(format=pyaudio.paInt16,
                                  channels=1,
                                  rate=16000,
                                  input=True,
                                  frames_per_buffer=4000)
        self.stream.start_stream()
        print("[VOSK] Microphone ready.")

    def listen(self):
        print("\n[VOSK] Listening... (Say something)")
        while True:
            data = self.stream.read(4000, exception_on_overflow=False)
            if STREAM_DEBUG:
                print("[VOSK DEBUG] Audio chunk received:", len(data))
            if self.recognizer.AcceptWaveform(data):
                result = json.loads(self.recognizer.Result())
                text_final = result.get("text", "").strip()
                if STREAM_DEBUG:
                    print("[VOSK DEBUG] FINAL:", text_final)
                return text_final
            else:
                partial = json.loads(self.recognizer.PartialResult()).get("partial", "")
                if partial and STREAM_DEBUG:
                    print("[VOSK DEBUG] PARTIAL:", partial)

# ------------------- Motor control wrapper (tool) -------------------
def import_motor_module(motor_dir):
    """
    Try to import motor_a_control from motor_dir, trying multiple fallbacks.
    Returns (module, error_string). module is None on failure.
    """
    tried = []
    # Common candidate paths to try if motor_dir is None/unset
    candidates = []
    if motor_dir:
        candidates.append(motor_dir)
    # Add sibling/relative paths that may be used
    candidates.extend([
        os.path.join(os.getcwd(), "motor_control"),
        os.path.join(os.path.dirname(os.getcwd()), "rasp", "motor_control"),
        "/home/admin/rasp/motor_control",
        "/home/pi/rasp/motor_control",
    ])
    # ensure uniqueness
    uniq = []
    for c in candidates:
        if c and c not in uniq:
            uniq.append(c)
    for path in uniq:
        if not path:
            continue
        tried.append(path)
        if STREAM_DEBUG:
            print(f"[MOTOR IMPORT] Trying to import from: {path}")
        if os.path.isdir(path):
            # temporarily add to sys.path
            if path not in sys.path:
                sys.path.insert(0, path)
            try:
                import motor_a_control
                if STREAM_DEBUG:
                    print(f"[MOTOR IMPORT] Successfully imported motor_a_control from {path}")
                return motor_a_control, None
            except Exception as e:
                # remove inserted path to avoid polluting environment (but keep other candidates)
                try:
                    if sys.path and sys.path[0] == path:
                        sys.path.pop(0)
                except Exception:
                    pass
                last_err = e
                if STREAM_DEBUG:
                    print(f"[MOTOR IMPORT] Failed at {path}: {e}")
                continue
        else:
            if STREAM_DEBUG:
                print(f"[MOTOR IMPORT] Path does not exist: {path}")
    # final attempt: try plain import without manipulating sys.path (maybe it is already resolvable)
    try:
        import motor_a_control
        return motor_a_control, None
    except Exception as e:
        last_err = e
    # if we got here, all attempts failed
    err_str = f"No module named 'motor_a_control' after trying paths: {uniq}. Last error: {last_err}"
    return None, err_str

def control_motors(action: str, speed: float = 0.4, motor_dir: str = None) -> str:
    """
    Perform the requested motor action using motor_a_control module.
    action: 'forward','backward','spin_left','spin_right','stop'
    speed: 0.0-1.0
    motor_dir: optional directory to find motor_a_control.py
    """
    try:
        speed = float(speed)
    except Exception:
        speed = 0.4
    speed = max(0.0, min(1.0, speed))

    mod, err = import_motor_module(motor_dir)
    if mod is None:
        # Return a sanitized message for TTS (do not leak tracebacks to TTS)
        if STREAM_DEBUG:
            print("[MOTOR TOOL] Import failed:", err)
        return f"motor import failed: No module named 'motor_a_control'"

    # expected functions in module
    # left_motor_forward, left_motor_backward, left_motor_stop,
    # right_motor_forward, right_motor_backward, right_motor_stop, all_stop
    try:
        if action == "forward":
            mod.left_motor_forward(speed)
            mod.right_motor_forward(speed)
            return f"moving forward at speed {speed:.2f}"
        elif action == "backward":
            mod.left_motor_backward(speed)
            mod.right_motor_backward(speed)
            return f"moving backward at speed {speed:.2f}"
        elif action == "spin_left":
            mod.left_motor_backward(speed)
            mod.right_motor_forward(speed)
            return f"spinning left at speed {speed:.2f}"
        elif action == "spin_right":
            mod.left_motor_forward(speed)
            mod.right_motor_backward(speed)
            return f"spinning right at speed {speed:.2f}"
        elif action == "stop":
            try:
                mod.all_stop()
            except Exception:
                try:
                    mod.left_motor_stop(); mod.right_motor_stop()
                except Exception:
                    pass
            return "stopped"
        else:
            return f"unknown action '{action}'"
    except Exception as e:
        traceback.print_exc()
        return f"error executing motor action: {e}"

# ------------------- Ollama streaming fallback (unchanged) -------------------
def stream_ollama(prompt, model, url, num_predict=20):
    import requests
    system_directive = (
        "SYSTEM: You are Buddy, an educational assistant who helps users learn. "
        "You MUST always respond briefly and concisely. Do not generate long paragraphs or lots of text at once. "
        "Avoid emojis and special characters in replies."
    )
    full_prompt = f"{system_directive}\n\nUSER: {prompt}\n\nASSISTANT:"
    if STREAM_DEBUG:
        print("[OLLAMA] Sending prompt (first 200 chars):", full_prompt[:200].replace("\n", " "))
    payload = {
        "model": model,
        "prompt": full_prompt,
        "stream": True,
        "options": {"num_predict": num_predict}
    }
    try:
        r = requests.post(url, json=payload, stream=True, timeout=30)
    except Exception as e:
        print("[OLLAMA] Request failed:", e)
        return ""
    if r.status_code != 200:
        print("[OLLAMA] Non-200 response:", r.status_code, r.text[:400])
        return ""
    reply_parts = []
    for raw in r.iter_lines():
        if not raw:
            continue
        try:
            obj = json.loads(raw.decode())
            piece = obj.get("response") or obj.get("text") or obj.get("token") or ""
        except Exception:
            piece = raw.decode(errors="ignore")
        if STREAM_DEBUG:
            print("[OLLAMA DEBUG] TOKEN:", piece[:120].replace("\n", " "))
        reply_parts.append(piece)
    raw_text = " ".join(reply_parts).strip()
    if STREAM_DEBUG:
        print("[OLLAMA] Raw assembled response (pre-clean):", raw_text[:400])
    cleaned = clean_received_text(raw_text)
    if STREAM_DEBUG:
        print("[OLLAMA] Cleaned response (asterisks removed):", cleaned[:400])
    return cleaned

# ------------------- Robust JSON/string parsing helpers (unchanged) -------------------
def try_parse_json_like_string(text: str):
    if not text:
        return None
    t = text.strip()
    candidates = [t]
    if (t.startswith('"') and t.endswith('"')) or (t.startswith("'") and t.endswith("'")):
        inner = t[1:-1]
        try:
            inner_unescaped = bytes(inner, "utf-8").decode("unicode_escape")
        except Exception:
            inner_unescaped = inner
        candidates.append(inner_unescaped)
    json_snips = re.findall(r'\{[^}]{0,2000}\}', t, flags=re.S) or []
    for sn in json_snips:
        candidates.append(sn)
    for cand in candidates:
        try:
            parsed = json.loads(cand)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            try:
                import ast
                parsed = ast.literal_eval(cand)
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                pass
    return None

def parse_command_from_text(text: str):
    if not text:
        return None, None
    parsed = try_parse_json_like_string(text)
    if parsed:
        if parsed.get("name") == "control_motors" or parsed.get("tool") == "control_motors":
            args = parsed.get("arguments") or {}
            action = args.get("action") or parsed.get("action")
            speed = args.get("speed", parsed.get("speed", 0.4))
            if action:
                try: return action, float(speed)
                except Exception: return action, 0.4
        elif "action" in parsed and parsed.get("action") in ("forward","backward","spin_left","spin_right","stop"):
            try: return parsed.get("action"), float(parsed.get("speed", 0.4))
            except Exception: return parsed.get("action"), 0.4
    low = text.lower()
    action = None
    if re.search(r'\b(go|move)\s+(forward|ahead|forwards)\b', low) or re.search(r'\bforward\b', low):
        action = "forward"
    elif re.search(r'\b(go|move)\s+(backward|backwards|back)\b', low) or re.search(r'\bbackward\b', low):
        action = "backward"
    elif re.search(r'\b(spin|turn|rotate)\s+(left)\b', low) or re.search(r'\bspin left\b', low):
        action = "spin_left"
    elif re.search(r'\b(spin|turn|rotate)\s+(right)\b', low) or re.search(r'\bspin right\b', low):
        action = "spin_right"
    elif re.search(r'\b(stop|halt|freeze|brake)\b', low):
        action = "stop"
    if action:
        m = re.search(r'(?:speed|at speed|at)\s*[:=]?\s*([0-9]*\.?[0-9]+)', low)
        if not m:
            speed = 0.4
        else:
            try:
                speed = float(m.group(1)); speed = max(0.0, min(1.0, speed))
            except Exception:
                speed = 0.4
        return action, speed
    return None, None

# ------------------- Ollama chat + tool-calling flow (unchanged except motor_dir passed) -------------------
def call_ollama_with_tools(prompt, model, chat_url, motor_dir=None, system_directive=None):
    import requests
    if system_directive is None:
        system_directive = (
            "SYSTEM: You are Buddy, an educational assistant who helps users learn. "
            "You MUST always respond briefly and concisely. Do not generate long paragraphs or lots of text at once. "
            "If you want to move the robot, call the tool named 'control_motors' with JSON arguments: "
            "{\"action\": \"forward|backward|spin_left|spin_right|stop\", \"speed\": <0.0-1.0>}. "
            "Do NOT call tools for anything else."
        )
    messages = [{"role":"system","content":system_directive},{"role":"user","content":prompt}]
    tools = [{
        "type":"function",
        "function":{
            "name":"control_motors",
            "description":"Control robot motors. Arguments: action and speed.",
            "parameters":{
                "type":"object",
                "required":["action"],
                "properties":{
                    "action":{"type":"string","description":"One of forward, backward, spin_left, spin_right, stop"},
                    "speed":{"type":"number","description":"Speed 0.0-1.0 (optional)."}
                }
            }
        }
    }]
    base_payload = {"model":model,"messages":messages,"tools":tools,"stream":False,"think":True}
    def do_request(payload):
        try:
            if STREAM_DEBUG:
                preview = {"model": payload.get("model"), "messages": [{"role":"user","content":str(prompt)[:200]}]}
                print("[OLLAMA CHAT] Sending /api/chat request. URL:", chat_url)
                print("[OLLAMA CHAT] Payload preview:", json.dumps(preview)[:1000])
            return requests.post(chat_url, json=payload, timeout=25)
        except Exception as e:
            print("[OLLAMA CHAT] Request to /api/chat failed:", e)
            return None
    r = do_request(base_payload)
    if r is None:
        return None, "error"
    if r.status_code == 400 and isinstance(r.text, str) and "does not support thinking" in r.text:
        print("[OLLAMA CHAT] Server rejected 'think' flag. Retrying without 'think'...")
        retry_payload = dict(base_payload); retry_payload.pop("think", None)
        r2 = do_request(retry_payload)
        if r2 is None: return None, "error"
        r = r2
    if r.status_code != 200:
        if STREAM_DEBUG:
            print("[OLLAMA CHAT] Non-200 from /api/chat:", r.status_code)
            print("[OLLAMA CHAT] Response body (first 2000 chars):", (r.text or "")[:2000])
        raw_body = r.text or ""
        parsed = try_parse_json_like_string(raw_body)
        if parsed:
            action = None; speed = 0.4
            if parsed.get("name") == "control_motors" or parsed.get("tool") == "control_motors":
                args = parsed.get("arguments") or {}
                action = args.get("action") or parsed.get("action")
                speed = args.get("speed", parsed.get("speed", 0.4))
            elif "action" in parsed:
                action = parsed.get("action"); speed = parsed.get("speed", 0.4)
            if action:
                res = control_motors(action, speed, motor_dir=motor_dir)
                return f"Executed motor command: {res}", "ok"
        return None, "error"
    raw_text = r.text or ""
    try:
        resp = r.json()
    except Exception as e:
        print("[OLLAMA CHAT] Failed to parse JSON from /api/chat response:", e)
        print("[OLLAMA CHAT] Raw response (preview):", raw_text[:2000])
        parsed = try_parse_json_like_string(raw_text)
        if parsed:
            action = None; speed = 0.4
            if parsed.get("name") == "control_motors" or parsed.get("tool") == "control_motors":
                args = parsed.get("arguments") or {}
                action = args.get("action") or parsed.get("action")
                speed = args.get("speed", parsed.get("speed", 0.4))
            elif "action" in parsed:
                action = parsed.get("action"); speed = parsed.get("speed", 0.4)
            if action:
                res = control_motors(action, speed, motor_dir=motor_dir)
                return f"Executed motor command: {res}", "ok"
        return None, "error"
    if LOG_TOOL_DEBUG:
        print("[OLLAMA CHAT] Parsed JSON top-level keys:", list(resp.keys()) if isinstance(resp, dict) else "not a dict")
        try:
            pp = pprint.pformat(resp, compact=True, width=160)
            print("[OLLAMA CHAT] Parsed response (compact preview):\n", pp[:4000])
        except Exception:
            pass
    assistant_message = None
    tool_calls = []
    if isinstance(resp, dict):
        if "message" in resp and isinstance(resp["message"], dict):
            assistant_message = resp["message"]
        elif "choices" in resp and isinstance(resp["choices"], list) and len(resp["choices"])>0:
            c0 = resp["choices"][0]
            assistant_message = c0.get("message") or c0
        else:
            assistant_message = resp
    else:
        assistant_message = resp
    def extract_tool_calls(obj):
        found = []
        if not obj: return found
        if isinstance(obj, dict):
            for key in ("tool_calls","toolCalls","function_calls","tool_call","function_call"):
                if key in obj and obj[key]:
                    if isinstance(obj[key], list): found.extend(obj[key])
                    else: found.append(obj[key])
            if "message" in obj and isinstance(obj["message"], dict):
                found.extend(extract_tool_calls(obj["message"]))
            if "choices" in obj and isinstance(obj["choices"], list):
                for c in obj["choices"]: found.extend(extract_tool_calls(c))
            if "function_call" in obj: found.append(obj["function_call"])
            for k,v in obj.items():
                if isinstance(v, dict) and any(x in k.lower() for x in ("tool","function","call")):
                    found.extend(extract_tool_calls(v))
        elif isinstance(obj, list):
            for el in obj: found.extend(extract_tool_calls(el))
        return found
    tool_calls = extract_tool_calls(assistant_message)
    if not tool_calls: tool_calls = extract_tool_calls(resp)
    if LOG_TOOL_DEBUG:
        print("[OLLAMA CHAT] tool_calls extracted (count):", len(tool_calls))
        if len(tool_calls)>0:
            for i,tc in enumerate(tool_calls):
                print(f"[OLLAMA CHAT] tool_call[{i}] raw:", pprint.pformat(tc)[:2000])
    assistant_content = ""
    if isinstance(assistant_message, dict):
        assistant_content = assistant_message.get("content") or assistant_message.get("text") or ""
    elif isinstance(assistant_message, str):
        assistant_content = assistant_message
    else:
        assistant_content = str(assistant_message)
    if STREAM_DEBUG:
        print("[OLLAMA CHAT] assistant_content (preview):", assistant_content[:800])
    # fallback parse if no structured tool calls
    if not tool_calls:
        action, speed = parse_command_from_text(assistant_content)
        if not action:
            action, speed = parse_command_from_text(raw_text)
        if action:
            if LOG_TOOL_DEBUG:
                print(f"[OLLAMA CHAT] Parsed fallback action='{action}' speed={speed}. Executing control_motors.")
            res = control_motors(action, speed, motor_dir=motor_dir)
            return f"Executed motor command: {res}", "ok"
        cleaned = clean_received_text(assistant_content)
        if LOG_TOOL_DEBUG:
            print("[OLLAMA CHAT] No tool_calls and no fallback command parsed. Returning assistant content.")
        return cleaned, "ok"
    # process structured tool_calls
    tool_results = []
    for tc in tool_calls:
        fname = None; arguments = {}
        try:
            if isinstance(tc, dict):
                if "function" in tc and isinstance(tc["function"], dict):
                    fname = tc["function"].get("name"); arguments = tc["function"].get("arguments") or {}
                elif "name" in tc and "arguments" in tc:
                    fname = tc.get("name"); arguments = tc.get("arguments") or {}
                elif "function_call" in tc and isinstance(tc["function_call"], dict):
                    fname = tc["function_call"].get("name") or tc["function_call"].get("function")
                    arguments = tc["function_call"].get("arguments") or {}
                else:
                    for k in ("name","function_name"):
                        if k in tc: fname = tc[k]
                    for k in ("arguments","args"):
                        if k in tc: arguments = tc[k] or {}
            elif isinstance(tc, str):
                try:
                    parsed = json.loads(tc)
                    if "function" in parsed:
                        fname = parsed["function"].get("name"); arguments = parsed["function"].get("arguments") or {}
                except Exception:
                    pass
        except Exception:
            pass
        if LOG_TOOL_DEBUG:
            print("[OLLAMA CHAT] Normalized tool call:", fname, "args:", arguments)
        if fname == "control_motors":
            action = arguments.get("action") or arguments.get("action_name") or ""
            speed = arguments.get("speed", 0.4)
            res_text = control_motors(action, speed, motor_dir=motor_dir)
            tool_results.append({"tool_name":"control_motors","content":res_text})
        else:
            tool_results.append({"tool_name": fname or "unknown", "content": "unknown tool"})
    # follow-up with tool results
    messages.append({"role":"assistant","content":assistant_content})
    for tr in tool_results:
        messages.append({"role":"tool","tool_name":tr["tool_name"],"content":str(tr["content"])})
    if LOG_TOOL_DEBUG:
        print("[OLLAMA CHAT] Follow-up messages preview (last few):")
        try:
            preview = {"messages": messages[-6:]}
            print(json.dumps(preview, default=str)[:2000])
        except Exception:
            pass
    followup_payload = {"model":model,"messages":messages,"tools":tools,"stream":False}
    try:
        if STREAM_DEBUG:
            print("[OLLAMA CHAT] Sending follow-up to /api/chat with tool results.")
        r2 = requests.post(chat_url, json=followup_payload, timeout=25)
    except Exception as e:
        print("[OLLAMA CHAT] Follow-up /api/chat failed:", e)
        return None, "error"
    if STREAM_DEBUG:
        print("[OLLAMA CHAT] Follow-up HTTP status:", r2.status_code)
    if r2.status_code != 200:
        print("[OLLAMA CHAT] Non-200 from follow-up /api/chat:", r2.status_code)
        print("[OLLAMA CHAT] Follow-up response body (preview):", (r2.text or "")[:2000])
        return None, "error"
    try:
        resp2 = r2.json()
    except Exception as e:
        print("[OLLAMA CHAT] Failed to parse JSON from follow-up /api/chat response:", e)
        print("[OLLAMA CHAT] Raw follow-up response (first 4000 chars):", r2.text[:4000])
        return None, "error"
    final_content = ""
    if isinstance(resp2, dict):
        if "message" in resp2 and isinstance(resp2["message"], dict):
            final_content = resp2["message"].get("content") or resp2["message"].get("text") or ""
        elif "choices" in resp2 and isinstance(resp2["choices"], list) and len(resp2["choices"]) > 0:
            final_content = resp2["choices"][0].get("message", {}).get("content") or resp2["choices"][0].get("message", {}).get("text") or resp2["choices"][0].get("content") or ""
        else:
            final_content = str(resp2)
    else:
        final_content = str(resp2)
    cleaned_final = clean_received_text(final_content if final_content else "")
    if LOG_TOOL_DEBUG:
        print("[OLLAMA CHAT] Final assistant content (preview):", cleaned_final[:800])
    return cleaned_final, "ok"

# ------------------- MAIN LOOP -------------------
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("piper_model")
    parser.add_argument("piper_config")
    parser.add_argument("--vosk", default="model")
    parser.add_argument("--model", default=DEFAULT_MODEL_NAME)
    parser.add_argument("--url", default=DEFAULT_OLLAMA_URL)
    parser.add_argument("--chat-url", default=DEFAULT_CHAT_URL)
    parser.add_argument("--num-predict", type=int, default=20)
    parser.add_argument("--motor-dir", default="/home/admin/rasp/motor_control",
                        help="Directory containing motor_a_control.py (default: /home/admin/rasp/motor_control)")
    args = parser.parse_args()

    # Print motor-dir being used
    if STREAM_DEBUG:
        print("[SYSTEM] motor_dir set to:", args.motor_dir)

    # Load Piper
    piper = PiperWrapper(args.piper_model, args.piper_config)

    # Load Vosk mic
    mic = VoiceListener(args.vosk)

    print("\n====== VOICE AI READY ======")
    print("Speak anytime. Say \"exit\" to stop.")
    print("============================\n")

    while True:
        text = mic.listen()
        if not text:
            print("[SYSTEM] No speech detected. Trying again...")
            continue

        print("\n[YOU]:", text)

        if text.lower() in ["exit", "quit", "stop"]:
            print("Goodbye!")
            break

        # First try the tool-calling chat flow. If it fails, fall back to streaming generate.
        try:
            llm_reply, status = call_ollama_with_tools(text, args.model, args.chat_url, motor_dir=args.motor_dir)
            if status != "ok" or not llm_reply:
                if STREAM_DEBUG:
                    print("[SYSTEM] Tool-calling path failed or returned nothing; falling back to streaming generate.")
                llm_reply = stream_ollama(text, args.model, args.url, num_predict=args.num_predict)
        except Exception as e:
            print("[SYSTEM] Error in tool-calling flow:", e)
            traceback.print_exc()
            llm_reply = stream_ollama(text, args.model, args.url, num_predict=args.num_predict)

        if not llm_reply or not llm_reply.strip():
            print("[SYSTEM] Empty response from Ollama.")
            continue

        # Clean the text for TTS: remove emojis & special characters, remove asterisks
        tts_text = clean_for_tts(llm_reply)

        if not tts_text:
            print("[SYSTEM] After cleaning, nothing left to speak.")
            continue

        if STREAM_DEBUG:
            print("[SPEAKING] Final TTS text (first 400 chars):", tts_text[:400])

        # Voice output
        wav = piper.synth(tts_text)
        try_playback(wav)

if __name__ == "__main__":
    main()
