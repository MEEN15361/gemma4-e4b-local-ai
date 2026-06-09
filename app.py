"""
Gemma 4 E4B - Local AI Chat
Chat-based AI assistant with command execution, file I/O, Python runner,
and permission controls (Full Auto / Safe Mode / Chat Only).

Run: py -3 app.py
"""

import gradio as gr
import ollama
import subprocess
import re
import os
import json
import tempfile
import platform
from datetime import datetime

# ===== Config =====
MODEL_NAME = "gemma4-e4b"
MAX_HISTORY = 20
MAX_AGENT_LOOPS = 15
MAX_AGENT_KEEP = 3            # sliding window: keep last N round-trips in context
MAX_NOTES_INJECT = 800        # max chars of _notes.txt to auto-inject into context
MAX_PLAN_INJECT = 400         # max chars of _plan.txt to auto-inject into context
MAX_READ_LINES = 200
MAX_CMD_OUTPUT = 10000       # max chars from a command (display)
MAX_MODEL_OUTPUT = 1500      # max chars sent back to model per action
CHATS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chats")

APPROVE_KEYWORDS = {
    "ok", "approve", "yes", "y",
    "ใช่", "อนุมัติ", "ทำเลย", "ได้", "เอา", "ตกลง",
}

BLOCKED_PATTERNS = [
    r"\brm\s+-rf\b", r"\bformat\s+[a-z]:", r"\bdel\s+/[sfq]", r"\bshutdown\b",
    r"\bmkfs\b", r"\bdd\s+if=", r"\bregedit\b", r"\breg\s+delete\b",
]

# Permission levels
PERM_FULL = "Full Auto"
PERM_SAFE = "Safe Mode"
PERM_CHAT = "Chat Only"


# ===== Action Execution =====
def is_dangerous_cmd(cmd: str) -> bool:
    cmd_lower = cmd.lower().strip()
    return any(re.search(p, cmd_lower) for p in BLOCKED_PATTERNS)


def run_command(cmd: str, timeout: int = 30) -> str:
    if is_dangerous_cmd(cmd):
        return f"[BLOCKED] {cmd}"
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            timeout=timeout, cwd=".", encoding="utf-8", errors="replace",
        )
        out = ""
        if result.stdout:
            out += result.stdout
        if result.stderr:
            out += ("\n" if out else "") + result.stderr
        out = out.strip()
        if not out:
            return f"(exit code: {result.returncode})"
        if len(out) > MAX_CMD_OUTPUT:
            out = out[:MAX_CMD_OUTPUT] + f"\n... (truncated, {len(out)} chars total)"
        return out
    except subprocess.TimeoutExpired:
        return f"[TIMEOUT] over {timeout}s"
    except Exception as e:
        return f"[ERROR] {e}"


def read_file(path: str) -> str:
    try:
        path = os.path.expanduser(path.strip().strip('"').strip("'"))
        if not os.path.exists(path):
            return f"[NOT FOUND] {path}"
        if os.path.isdir(path):
            items = os.listdir(path)
            listing = "\n".join(f"  {i}" for i in items[:50])
            suffix = f"\n  ... ({len(items)} total)" if len(items) > 50 else ""
            return f"[DIR] {path}\n{listing}{suffix}"
        size = os.path.getsize(path)
        if size > 500_000:
            return f"[TOO LARGE] {path} ({size:,} bytes)"
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        if len(lines) > MAX_READ_LINES:
            text = "".join(lines[:MAX_READ_LINES])
            text += f"\n... (truncated {MAX_READ_LINES}/{len(lines)} lines)"
        else:
            text = "".join(lines)
        return text
    except Exception as e:
        return f"[ERROR] {e}"


def write_file(path: str, content: str) -> str:
    try:
        path = os.path.expanduser(path.strip().strip('"').strip("'"))
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
        return f"[OK] {path} ({len(content)} chars)"
    except Exception as e:
        return f"[ERROR] {e}"


def run_python(code: str) -> str:
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8",
        ) as f:
            f.write(code)
            tmp_path = f.name
        result = subprocess.run(
            ["py", "-3", tmp_path],
            capture_output=True, text=True, timeout=30,
            encoding="utf-8", errors="replace",
        )
        out = ""
        if result.stdout:
            out += result.stdout
        if result.stderr:
            out += ("\n" if out else "") + result.stderr
        return out.strip() or f"(exit code: {result.returncode})"
    except subprocess.TimeoutExpired:
        return "[TIMEOUT] over 30s"
    except Exception as e:
        return f"[ERROR] {e}"
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


def execute_action(action: dict) -> str:
    t = action["type"]
    if t == "cmd":
        return run_command(action["cmd"])
    elif t == "read":
        return read_file(action["path"])
    elif t == "write":
        return write_file(action["path"], action["content"])
    elif t == "python":
        return run_python(action["code"])
    return "[ERROR] unknown action"


# ===== Action Parsing =====
def extract_actions(text: str) -> list[dict]:
    actions = []
    for m in re.finditer(r"<cmd>(.*?)</cmd>", text, re.DOTALL):
        actions.append({"type": "cmd", "cmd": m.group(1).strip()})
    for m in re.finditer(r"<read>(.*?)</read>", text, re.DOTALL):
        actions.append({"type": "read", "path": m.group(1).strip()})
    for m in re.finditer(r'<write\s+path="([^"]+)">(.*?)</write>', text, re.DOTALL):
        actions.append({"type": "write", "path": m.group(1).strip(), "content": m.group(2)})
    for m in re.finditer(r"<python>(.*?)</python>", text, re.DOTALL):
        actions.append({"type": "python", "code": m.group(1).strip()})
    return actions


def clean_tags(text: str) -> str:
    """Replace action tags with readable text for display while streaming"""
    text = re.sub(r"<cmd>(.*?)</cmd>", r"`\1`", text, flags=re.DOTALL)
    text = re.sub(r"<read>(.*?)</read>", r"*reading \1...*", text, flags=re.DOTALL)
    text = re.sub(
        r'<write\s+path="([^"]+)">(.*?)</write>',
        r"*writing \1...*",
        text, flags=re.DOTALL,
    )
    text = re.sub(
        r"<python>(.*?)</python>",
        r"*running python...*",
        text, flags=re.DOTALL,
    )
    return text


# ===== Permission Logic =====
def action_needs_approval(action: dict) -> bool:
    """In Safe Mode: reads and safe cmds are auto, everything else asks"""
    if action["type"] == "read":
        return False
    if action["type"] == "cmd" and not is_dangerous_cmd(action.get("cmd", "")):
        return False
    return True


def split_actions(actions: list[dict], perm: str) -> tuple[list, list]:
    """Split into (auto_execute, needs_approval)"""
    if perm == PERM_FULL:
        return actions, []
    if perm == PERM_CHAT:
        return [], []
    # Safe Mode
    auto, ask = [], []
    for a in actions:
        (ask if action_needs_approval(a) else auto).append(a)
    return auto, ask


# ===== Display Formatting =====
def fmt_result(action: dict, result: str) -> str:
    labels = {
        "cmd": lambda a: f"Command: `{a['cmd']}`",
        "read": lambda a: f"Read: `{a['path']}`",
        "write": lambda a: f"Write: `{a['path']}`",
        "python": lambda a: "Python",
    }
    label = labels.get(action["type"], lambda a: "Action")(action)
    display_result = result
    if len(result) > 2000:
        display_result = result[:2000] + f"\n... (truncated, {len(result)} chars total)"
    return f"\n\n---\n**{label}**\n```\n{display_result}\n```"


def fmt_for_model(action: dict, result: str) -> str:
    """Format result for model context - truncated to preserve context window"""
    if action["type"] == "cmd":
        header = f"$ {action['cmd']}\n"
    elif action["type"] == "read":
        header = f"[Read {action['path']}]\n"
    elif action["type"] == "write":
        header = f"[Write {action['path']}]\n"
    elif action["type"] == "python":
        header = f"[Python]\n"
    else:
        header = ""

    if len(result) > MAX_MODEL_OUTPUT:
        truncated = result[:MAX_MODEL_OUTPUT]
        truncated += (
            f"\n... (TRUNCATED {MAX_MODEL_OUTPUT}/{len(result)} chars. "
            f"IMPORTANT: Save key findings to _notes.txt NOW before they are lost from context. "
            f"Use more specific commands to get details.)"
        )
        return header + truncated
    return header + result


def fmt_pending(actions: list[dict]) -> str:
    text = "\n\n---\n**Pending Approval:**\n"
    for a in actions:
        if a["type"] == "cmd":
            text += f"- Command: `{a['cmd']}`\n"
        elif a["type"] == "write":
            preview = a["content"][:500]
            if len(a["content"]) > 500:
                preview += "..."
            text += f"- Write `{a['path']}`:\n```\n{preview}\n```\n"
        elif a["type"] == "python":
            text += f"- Python:\n```python\n{a['code']}\n```\n"
    text += '\n**ok** / **approve** = proceed | type anything else = cancel'
    return text


def action_status(action: dict) -> str:
    """Human-readable status for an action being executed"""
    if action["type"] == "cmd":
        return f"Running: {action['cmd']}"
    elif action["type"] == "read":
        return f"Reading: {action['path']}"
    elif action["type"] == "write":
        return f"Writing: {action['path']}"
    elif action["type"] == "python":
        return "Running Python..."
    return "Working..."


# ===== Chat Logic =====
def get_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            item.get("text", "") if isinstance(item, dict) else str(item)
            for item in content
        )
    return str(content)


CONTINUE_PROMPT = (
    "[System: step {step} results]\n{results}\n"
    "BEFORE doing anything else: save key findings from above to _notes.txt using <python> append.\n"
    "Then decide next action:\n"
    "- Task NOT done? Do the next step immediately (use tool tags).\n"
    "- Step FAILED? Try a different approach.\n"
    "- Task DONE? Summarize what you did for the user.\n"
    "Do NOT stop to confirm. Keep working."
)


def _split_base_and_rounds(messages):
    """Separate original user context from agent round-trip pairs.
    Agent rounds are (assistant response, continue prompt) pairs where
    the continue prompt starts with '[System: action results]'.
    """
    base = []
    rounds = []
    i = 0
    while i < len(messages):
        # Detect agent round: assistant + continue-prompt pair
        if (i + 1 < len(messages)
                and messages[i]["role"] == "assistant"
                and messages[i + 1]["role"] == "user"
                and messages[i + 1].get("content", "").startswith("[System: action results]")):
            rounds.append((messages[i]["content"], messages[i + 1]["content"]))
            i += 2
        else:
            base.append(messages[i])
            i += 1
    return base, rounds


def _read_working_files():
    """Read _plan.txt and _notes.txt for auto-injection into context.
    Returns formatted string, or empty if no files exist.
    Keeps tail of notes (most recent findings) to stay within budget.
    """
    parts = []
    for fname, max_chars in [("_plan.txt", MAX_PLAN_INJECT), ("_notes.txt", MAX_NOTES_INJECT)]:
        if os.path.exists(fname):
            try:
                with open(fname, "r", encoding="utf-8", errors="replace") as f:
                    text = f.read().strip()
                if text:
                    if len(text) > max_chars:
                        text = "..." + text[-max_chars:]
                    parts.append(f"[{fname}]\n{text}")
            except Exception:
                pass
    return "\n\n".join(parts)


def _build_context(base_msgs, rounds):
    """Build model context with sliding window over agent rounds.
    When old rounds are dropped, auto-injects _notes.txt and _plan.txt
    so the model doesn't need to waste a round reading them back.
    """
    ctx = list(base_msgs)
    if len(rounds) > MAX_AGENT_KEEP:
        dropped = len(rounds) - MAX_AGENT_KEEP

        # Auto-inject working files as memory aid
        notes = _read_working_files()
        if notes:
            ctx.append({
                "role": "user",
                "content": (
                    f"[System: {dropped} earlier steps done, removed from memory. "
                    f"Your saved files:\n{notes}]\n"
                    f"Continue working. Save new findings to _notes.txt."
                ),
            })
        else:
            ctx.append({
                "role": "user",
                "content": (
                    f"[System: {dropped} earlier steps done, removed from memory. "
                    f"WARNING: No _notes.txt found — your earlier work may be lost! "
                    f"Save progress to _notes.txt NOW.]"
                ),
            })
        ctx.append({
            "role": "assistant",
            "content": "OK, continuing with the task.",
        })
    for asst_content, user_content in rounds[-MAX_AGENT_KEEP:]:
        ctx.append({"role": "assistant", "content": asst_content})
        ctx.append({"role": "user", "content": user_content})
    return ctx


def _rebuild_full_messages(base_msgs, rounds):
    """Reconstruct full message list from base + rounds (for state saving)."""
    full = list(base_msgs)
    for asst_content, user_content in rounds:
        full.append({"role": "assistant", "content": asst_content})
        full.append({"role": "user", "content": user_content})
    return full


def agent_loop(messages, display, perm, pending_state, max_loops=MAX_AGENT_LOOPS):
    """Core loop: stream AI -> extract actions -> execute -> feed back -> repeat.
    Uses sliding window (MAX_AGENT_KEEP) to prevent context overflow.
    Yields: (display_text, has_pending, status_text)
    """

    # Separate base context from any existing agent rounds (e.g. from Continue)
    base_msgs, rounds = _split_base_and_rounds(messages)

    for loop_i in range(max_loops):
        # Build context with sliding window
        ctx = _build_context(base_msgs, rounds)

        # --- Stream AI response ---
        response_text = ""
        step = loop_i + len(rounds) + 1
        status = f"Thinking... (step {step})" if step > 1 else "Thinking..."
        try:
            stream = ollama.chat(model=MODEL_NAME, messages=ctx, stream=True)
            for chunk in stream:
                token = chunk["message"]["content"]
                response_text += token
                yield display + clean_tags(response_text), False, status
        except Exception as e:
            error_msg = f"\n\n**Error:** {e}"
            if "connection" in str(e).lower():
                error_msg += "\n\nCheck: Ollama running? (`ollama serve`)"
            yield display + error_msg, False, ""
            return

        display += clean_tags(response_text)

        # --- Extract actions ---
        actions = extract_actions(response_text)

        if not actions:
            yield display, False, ""
            return

        if perm == PERM_CHAT:
            display += "\n\n---\n*Chat Only mode - actions not executed*"
            yield display, False, ""
            return

        auto_actions, ask_actions = split_actions(actions, perm)

        # --- Execute auto actions ---
        results_text = ""
        for a in auto_actions:
            yield display, False, action_status(a)
            result = execute_action(a)
            display += fmt_result(a, result)
            results_text += fmt_for_model(a, result) + "\n\n"
            yield display, False, ""

        # --- Handle approval-needed actions ---
        if ask_actions:
            display += fmt_pending(ask_actions)
            full_msgs = _rebuild_full_messages(base_msgs, rounds)
            full_msgs.append({"role": "assistant", "content": response_text})
            pending_state["actions"] = ask_actions
            pending_state["context"] = full_msgs
            pending_state["auto_results"] = results_text
            yield display, True, "Waiting for approval..."
            return

        if not results_text:
            yield display, False, ""
            return

        # --- Save this round for sliding window ---
        rounds.append((
            response_text,
            CONTINUE_PROMPT.format(step=step, results=results_text),
        ))
        display += "\n"

    # Max loops reached - allow user to continue
    total_steps = len(rounds)
    pending_state["continue"] = {
        "messages": _rebuild_full_messages(base_msgs, rounds),
        "display": display,
    }
    yield (
        display + f"\n\n---\n*Reached {total_steps} steps — click **Continue** to keep going, or type a new message.*",
        "continue",
        "",
    )


def chat(message, history, permission, pending_state, summary=""):
    """Main chat entry point - handles normal chat and approval flow
    Yields: (display_text, has_pending, status_text)
    """

    message = get_text(message)
    msg_lower = message.strip().lower()

    # --- Handle Continue (resume agent loop) ---
    if pending_state.get("continue") and msg_lower in (APPROVE_KEYWORDS | {"continue", "cont", "ต่อ", "ทำต่อ"}):
        cont = pending_state.pop("continue")
        for resp, hp, status in agent_loop(
            cont["messages"], cont["display"] + "\n", permission, pending_state,
        ):
            yield resp, hp, status
        return

    # --- Handle approval of pending actions ---
    if pending_state.get("actions") and msg_lower in APPROVE_KEYWORDS:
        actions = pending_state["actions"]
        ctx = list(pending_state["context"])  # copy (already has summary)
        auto_results = pending_state.get("auto_results", "")
        pending_state["actions"] = None  # clear pending

        # Execute approved actions
        display = ""
        results_text = auto_results
        for a in actions:
            yield display, False, action_status(a)
            result = execute_action(a)
            display += fmt_result(a, result)
            results_text += fmt_for_model(a, result) + "\n\n"
        yield display, False, ""

        # Continue agent loop with combined results
        ctx.append({
            "role": "user",
            "content": CONTINUE_PROMPT.format(step=1, results=results_text),
        })
        for resp, has_pending, status in agent_loop(
            ctx, display + "\n", permission, pending_state, MAX_AGENT_LOOPS - 1,
        ):
            yield resp, has_pending, status
        return

    # --- Clear pending on any non-approval message ---
    pending_state["actions"] = None
    pending_state.pop("continue", None)

    # --- Build Ollama messages from history ---
    messages = []

    # Inject summary as context reminder
    if summary and summary.strip():
        messages.append({
            "role": "user",
            "content": f"[Context from our conversation so far: {summary.strip()}]",
        })
        messages.append({
            "role": "assistant",
            "content": "Understood, I'll keep that context in mind.",
        })

    for msg in history:
        content = get_text(msg["content"]).strip()
        if content:
            messages.append({"role": msg["role"], "content": content})
    messages.append({"role": "user", "content": get_text(message)})

    # --- Run agent loop ---
    for resp, has_pending, status in agent_loop(messages, "", permission, pending_state):
        yield resp, has_pending, status


# ===== Manual Command =====
def execute_manual(cmd):
    if not cmd.strip():
        return ""
    return run_command(cmd.strip())


# ===== Ollama Status =====
def check_status():
    try:
        models = ollama.list()
        names = [m.model for m in models.models]
        found = any(MODEL_NAME in n for n in names)
        s = f"**Ollama:** Connected ({len(names)} models)\n"
        for n in names:
            mark = " << active" if MODEL_NAME in n else ""
            s += f"- `{n}`{mark}\n"
        if not found:
            s += f"\n**Warning:** `{MODEL_NAME}` not found\n"
            s += f"Run: `ollama create {MODEL_NAME} -f Modelfile`"
        return s
    except Exception as e:
        return f"**Ollama:** Not connected\n\nError: {e}\n\nRun `ollama serve` first"


# ===== Chat History =====
def _ensure_chats_dir():
    os.makedirs(CHATS_DIR, exist_ok=True)


def save_chat(history, summary):
    """Save current chat + summary to a JSON file"""
    if not history:
        return gr.update(), "No chat to save"
    _ensure_chats_dir()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    label = "chat"
    for msg in history:
        if msg.get("role") == "user":
            text = get_text(msg["content"]).strip()[:40]
            text = re.sub(r'[\\/:*?"<>|]', '', text)
            if text:
                label = text
            break
    filename = f"{ts}_{label}.json"
    filepath = os.path.join(CHATS_DIR, filename)
    clean = []
    for msg in history:
        clean.append({
            "role": msg["role"],
            "content": get_text(msg["content"]),
        })
    data = {"history": clean, "summary": summary or ""}
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return list_saved_chats(), f"Saved: {filename}"


def list_saved_chats():
    """Return dropdown choices of saved chats"""
    _ensure_chats_dir()
    files = sorted(
        [f for f in os.listdir(CHATS_DIR) if f.endswith(".json")],
        reverse=True,
    )
    if not files:
        return gr.update(choices=[], value=None)
    # Format display: "12:30 - first message..."
    choices = []
    for f in files[:20]:  # show latest 20
        name = f.replace(".json", "")
        parts = name.split("_", 2)
        if len(parts) >= 3:
            time_str = parts[1][:2] + ":" + parts[1][2:4]
            date_str = parts[0][6:8] + "/" + parts[0][4:6]
            label_str = parts[2] if len(parts) > 2 else ""
            display = f"{date_str} {time_str} - {label_str}"
        else:
            display = name
        choices.append((display, f))
    return gr.update(choices=choices, value=None)


def load_chat(filename):
    """Load a saved chat + summary"""
    if not filename:
        return [], "", "No chat selected"
    filepath = os.path.join(CHATS_DIR, filename)
    if not os.path.exists(filepath):
        return [], "", f"File not found: {filename}"
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
    # Support old format (plain list) and new format (dict with summary)
    if isinstance(data, list):
        return data, "", f"Loaded: {filename}"
    return data.get("history", []), data.get("summary", ""), f"Loaded: {filename}"


def delete_chat(filename):
    """Delete a saved chat"""
    if not filename:
        return gr.update(), "No chat selected"
    filepath = os.path.join(CHATS_DIR, filename)
    if os.path.exists(filepath):
        os.remove(filepath)
    return list_saved_chats(), f"Deleted: {filename}"


# ===== Summary =====
def generate_summary(history, existing_summary):
    """Ask the model to summarize the conversation so far"""
    if not history or len(history) < 2:
        return existing_summary or "", "*Need at least 1 exchange to summarize*"

    # Build condensed conversation for the model
    lines = []
    if existing_summary and existing_summary.strip():
        lines.append(f"[Previous summary: {existing_summary.strip()}]")
    for msg in history[-16:]:  # last 16 messages to stay within context
        role = "User" if msg["role"] == "user" else "AI"
        text = get_text(msg["content"]).strip()
        if len(text) > 300:
            text = text[:300] + "..."
        lines.append(f"{role}: {text}")

    prompt = (
        "Summarize this conversation in 2-3 short sentences. "
        "Include: what the user wants, what was done, what is pending. "
        "Write the summary only, no extra text.\n\n"
        + "\n".join(lines)
    )

    try:
        response = ollama.chat(
            model=MODEL_NAME,
            messages=[{"role": "user", "content": prompt}],
        )
        summary = response["message"]["content"].strip()
        return summary, "*Summary updated*"
    except Exception as e:
        return existing_summary or "", f"*Error: {e}*"


# ===== Gradio UI =====
def build_ui():
    with gr.Blocks(title="Gemma 4 E4B - AI Chat") as app:

        pending = gr.State({
            "actions": None, "context": None, "auto_results": None,
        })

        gr.Markdown(
            "# Gemma 4 E4B - Local AI Chat\n"
            "Chat-based AI assistant | Command, File I/O, Python"
        )

        with gr.Row():
            # ---- Main chat area ----
            with gr.Column(scale=4):
                chatbot = gr.Chatbot(height=500)
                status_line = gr.Markdown("", elem_id="status-line")
                with gr.Row():
                    msg = gr.Textbox(
                        placeholder="Type a message... (e.g. 'read app.py', 'open notepad', 'create hello.py')",
                        show_label=False, container=False,
                        autofocus=True, scale=6,
                    )
                    stop_btn = gr.Button(
                        "Stop", variant="stop",
                        visible=False, scale=1, min_width=80,
                    )
                    continue_btn = gr.Button(
                        "Continue", variant="primary",
                        visible=False, scale=1, min_width=100,
                    )
                    approve_btn = gr.Button(
                        "Approve", variant="primary",
                        visible=False, scale=1, min_width=100,
                    )

            # ---- Sidebar ----
            with gr.Column(scale=1):
                gr.Markdown("### Settings")
                permission = gr.Radio(
                    choices=[PERM_FULL, PERM_SAFE, PERM_CHAT],
                    value=PERM_SAFE,
                    label="Permission Level",
                    info="Full Auto = do everything | Safe = ask before write/python | Chat = talk only",
                )

                gr.Markdown("---")
                gr.Markdown("### Summary")
                summary_box = gr.Textbox(
                    placeholder="Context summary will appear here...",
                    label="Conversation Context",
                    lines=3, max_lines=6,
                    info="AI uses this as memory. Auto or manual edit.",
                )
                with gr.Row():
                    summarize_btn = gr.Button("Summarize", variant="secondary", scale=1)
                    clear_summary_btn = gr.Button("Clear", variant="secondary", scale=1)
                summary_status = gr.Markdown("")

                gr.Markdown("---")
                clear_btn = gr.Button("Clear Chat", variant="secondary")
                status_btn = gr.Button("Check Ollama", variant="secondary")
                status_out = gr.Markdown("*Click to check*")

                gr.Markdown("---")
                gr.Markdown("### Chat History")
                save_btn = gr.Button("Save Chat", variant="secondary")
                chat_dropdown = gr.Dropdown(
                    label="Saved Chats", choices=[], interactive=True,
                )
                with gr.Row():
                    load_btn = gr.Button("Load", variant="primary", scale=1)
                    delete_btn = gr.Button("Delete", variant="secondary", scale=1)
                history_status = gr.Markdown("")

                gr.Markdown("---")
                gr.Markdown("### Manual Command")
                manual_cmd = gr.Textbox(placeholder="command...", show_label=False)
                run_btn = gr.Button("Run", variant="primary")
                cmd_out = gr.Code(label="Output", language="shell")

        # ===== Event Handlers =====
        def user_submit(message, history):
            if not message.strip():
                return message, history
            history = history + [{"role": "user", "content": message}]
            if len(history) > MAX_HISTORY * 2:
                history = history[-(MAX_HISTORY * 2):]
            return "", history

        def bot_respond(history, perm, pend, ctx_summary):
            if not history or history[-1]["role"] != "user":
                yield history, pend, gr.update(visible=False), gr.update(visible=False), gr.update(visible=False), ""
                return  # outputs: chatbot, pending, approve_btn, continue_btn, stop_btn, status_line
            user_msg = history[-1]["content"]
            history.append({"role": "assistant", "content": ""})

            has_pending = False
            for response, hp, status in chat(user_msg, history[:-1], perm, pend, ctx_summary):
                history[-1]["content"] = response
                has_pending = hp
                show_approve = (hp is True)
                show_continue = (hp == "continue")
                yield (
                    history, pend,
                    gr.update(visible=show_approve),    # approve_btn
                    gr.update(visible=show_continue),   # continue_btn
                    gr.update(visible=True),             # stop_btn
                    f"*{status}*" if status else "",     # status_line
                )

            show_approve = (has_pending is True)
            show_continue = (has_pending == "continue")
            yield (
                history, pend,
                gr.update(visible=show_approve),    # approve_btn
                gr.update(visible=show_continue),   # continue_btn
                gr.update(visible=False),            # stop_btn
                "",                                  # status_line
            )

        def on_approve(history, pend):
            if not pend.get("actions"):
                return history
            return history + [{"role": "user", "content": "ok"}]

        def on_stop():
            return gr.update(visible=False), gr.update(visible=False), gr.update(visible=False), "*Stopped.*"

        def on_continue(history, pend):
            """Add 'continue' message to resume agent loop"""
            if not pend.get("continue"):
                return history
            return history + [{"role": "user", "content": "continue"}]

        # Chat submit chain
        chat_event = msg.submit(
            user_submit, [msg, chatbot], [msg, chatbot],
        ).then(
            bot_respond,
            [chatbot, permission, pending, summary_box],
            [chatbot, pending, approve_btn, continue_btn, stop_btn, status_line],
        )

        # Stop button: cancel generation + cleanup
        stop_btn.click(
            on_stop,
            outputs=[stop_btn, continue_btn, approve_btn, status_line],
            cancels=[chat_event],
        )

        # Approve button -> adds "ok" then triggers bot
        approve_event = approve_btn.click(
            on_approve, [chatbot, pending], [chatbot],
        ).then(
            bot_respond,
            [chatbot, permission, pending, summary_box],
            [chatbot, pending, approve_btn, continue_btn, stop_btn, status_line],
        )

        # Continue button -> adds "continue" then resumes agent loop
        continue_event = continue_btn.click(
            on_continue, [chatbot, pending], [chatbot],
        ).then(
            bot_respond,
            [chatbot, permission, pending, summary_box],
            [chatbot, pending, approve_btn, continue_btn, stop_btn, status_line],
        )

        # Stop cancels all generation events
        stop_btn.click(
            on_stop,
            outputs=[stop_btn, continue_btn, approve_btn, status_line],
            cancels=[approve_event, continue_event],
        )

        # Summary
        summarize_btn.click(
            generate_summary,
            inputs=[chatbot, summary_box],
            outputs=[summary_box, summary_status],
        )
        clear_summary_btn.click(
            lambda: ("", ""),
            outputs=[summary_box, summary_status],
        )

        # Clear chat (also clears summary)
        def clear_all():
            empty_pending = {
                "actions": None, "context": None, "auto_results": None,
            }
            return [], empty_pending, gr.update(visible=False), gr.update(visible=False), gr.update(visible=False), "", ""

        clear_btn.click(
            clear_all,
            outputs=[chatbot, pending, approve_btn, continue_btn, stop_btn, status_line, summary_box],
        )

        # Chat history (save/load include summary)
        save_btn.click(
            save_chat, inputs=[chatbot, summary_box],
            outputs=[chat_dropdown, history_status],
        )
        load_btn.click(
            load_chat, inputs=[chat_dropdown],
            outputs=[chatbot, summary_box, history_status],
        )
        delete_btn.click(
            delete_chat, inputs=[chat_dropdown],
            outputs=[chat_dropdown, history_status],
        )
        # Populate dropdown on app load
        app.load(list_saved_chats, outputs=[chat_dropdown])

        # Status & manual command
        status_btn.click(check_status, outputs=status_out)
        run_btn.click(execute_manual, inputs=manual_cmd, outputs=cmd_out)
        manual_cmd.submit(execute_manual, inputs=manual_cmd, outputs=cmd_out)

    return app


# ===== Main =====
if __name__ == "__main__":
    print("=" * 50)
    print("  Gemma 4 E4B - Local AI Chat")
    print("=" * 50)
    print(f"  Platform: {platform.system()} {platform.release()}")
    print(f"  Model:    {MODEL_NAME}")
    print()

    try:
        models = ollama.list()
        names = [m.model for m in models.models]
        found = any(MODEL_NAME in n for n in names)
        print(f"  Ollama:   Connected ({len(names)} models)")
        if found:
            print(f"  Model:    '{MODEL_NAME}' found")
        else:
            print(f"  Model:    '{MODEL_NAME}' NOT FOUND")
            print(f"  Run: ollama create {MODEL_NAME} -f Modelfile")
    except Exception:
        print("  Ollama:   Not running")
        print("  Start:    ollama serve")

    print()
    print("  Tools:    cmd, read, write, python")
    print("  Default:  Safe Mode (ask before write/python)")
    print()
    print("  Starting Gradio UI...")
    print("=" * 50)

    app = build_ui()
    app.launch(
        server_name="0.0.0.0",
        server_port=7860,
        share=False,
        inbrowser=True,
        theme=gr.themes.Soft(primary_hue="blue"),
    )
