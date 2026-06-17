import tkinter as tk
from tkinter import filedialog, messagebox
import re
import sys
from io import StringIO
import threading
import queue
import time
# =========================
# BlueStar Transformer
# =========================
def normalize_value(value):
    v = value.strip()
    low = v.lower()
    if low == "yes":
        return "True"
    if low == "no":
        return "False"
    if low == "true":
        return "True"
    if low == "false":
        return "False"
    if re.fullmatch(r'-?\d+', v):
        return v
    if re.fullmatch(r'-?\d+\.\d+', v):
        return v
    if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
        return v
    return f'"{v}"'

def count_indent(line):
    count = 0
    for ch in line:
        if ch == ' ':
            count += 1
        elif ch == '\t':
            count += 4
        else:
            break
    return count

def strip_indent(line, n):
    i = 0
    removed = 0
    while i < len(line) and removed < n:
        if line[i] == ' ':
            removed += 1
        elif line[i] == '\t':
            removed += 4
        else:
            break
        i += 1
    return line[i:]

def transform_simple_line(raw):
    line = raw.strip()
    if not line or line.startswith("com="):
        return None
    # say=a
    m = re.match(r'^say\s*=\s*(.+)$', line)
    if m:
        return f'print({m.group(1).strip()})'
    # update var:a (in=123)
    m = re.match(r'^update\s+var:(\w+)\s*\(\s*(?:type=(\w+)\s+)?in=(.+)\)$', line)
    if m:
        var_name = m.group(1)
        var_type = m.group(2)
        value = m.group(3).strip()
        if var_type is None:
            return f'{var_name} = {value}'
        vt = var_type.lower()
        if vt == "num":
            return f'{var_name} = {value}'
        elif vt == "str":
            return f'{var_name} = {normalize_value(value)}'
        elif vt == "bol":
            low = value.lower()
            if low in ("true", "yes"):
                return f'{var_name} = True'
            elif low in ("false", "no"):
                return f'{var_name} = False'
            return f'{var_name} = {value}'
        return f'{var_name} = {value}'
    # data num a(1)
    m = re.match(r'^data\s+num\s+(\w+)\(([^)]*)\)$', line)
    if m:
        var = m.group(1)
        val = m.group(2).strip()
        return f'{var} = {val}'
    # data str a(hello)
    m = re.match(r'^data\s+str\s+(\w+)\(([^)]*)\)$', line)
    if m:
        var = m.group(1)
        val = m.group(2).strip()
        return f'{var} = {normalize_value(val)}'
    # data bol a(true)
    m = re.match(r'^data\s+bol\s+(\w+)\(([^)]*)\)$', line, re.IGNORECASE)
    if m:
        var = m.group(1)
        val = m.group(2).strip().lower()
        if val in ("true", "yes"):
            return f'{var} = True'
        if val in ("false", "no"):
            return f'{var} = False'
        return f'{var} = {val}'
    # compatibility
    m = re.match(r'^data\s+word\s+(?:=\s*)?(\w+)\(([^)]*)\)$', line)
    if m:
        return f'{m.group(1)} = {normalize_value(m.group(2).strip())}'
    m = re.match(r'^data\s+number\s+(?:=\s*)?(\w+)\(([^)]*)\)$', line)
    if m:
        return f'{m.group(1)} = {m.group(2).strip()}'
    m = re.match(r'^data\s+deal\s+(?:=\s*)?(\w+)\((yes|no|true|false)\)$', line, re.IGNORECASE)
    if m:
        var = m.group(1)
        val = m.group(2).lower()
        return f'{var} = True' if val in ("yes", "true") else f'{var} = False'
    # a x b -> a*b
    line = re.sub(r'(\w+)\s*x\s*(\w+)', r'\1*\2', line)
    return line

def parse_header(line):
    line = line.strip()
    m = re.match(r'^(if|while)\s+(yes|no|true|false)\s*/$', line, re.IGNORECASE)
    if m:
        kind = m.group(1)
        val = m.group(2).lower()
        expr = "True" if val in ("yes", "true") else "False"
        return kind, expr
    m = re.match(r'^(if|while)\s+(.+?)\s*(==|!=|>=|<=|>|<|=)\s*(.+?)\s*/$', line)
    if m:
        kind = m.group(1)
        left = m.group(2).strip()
        op = m.group(3)
        right = m.group(4).strip()
        if op == "=":
            op = "=="
        if right.lower() in ("yes", "true"):
            right = "True"
        elif right.lower() in ("no", "false"):
            right = "False"
        elif not re.fullmatch(r'-?\d+(\.\d+)?', right):
            if not ((right.startswith('"') and right.endswith('"')) or (right.startswith("'") and right.endswith("'"))):
                right = f'"{right}"'
        return kind, f'{left} {op} {right}'
    return None

def transform_lines(lines, start=0, base_indent=0):
    result = []
    i = start
    while i < len(lines):
        raw = lines[i].rstrip('\n')
        if not raw.strip():
            i += 1
            continue
        indent = count_indent(raw)
        if indent < base_indent:
            break
        stripped = raw.strip()
        header = parse_header(stripped)
        if header:
            kind, expr = header
            block = []
            i += 1
            while i < len(lines):
                nxt = lines[i].rstrip('\n')
                if not nxt.strip():
                    block.append("")
                    i += 1
                    continue
                nxt_indent = count_indent(nxt)
                if nxt_indent <= indent:
                    break
                block.append(strip_indent(nxt, indent + 4))
                i += 1
            inner = transform_lines(block, 0, 0)
            if inner.strip():
                result.append(" " * indent + f"{kind} {expr}:")
                for x in inner.splitlines():
                    result.append(" " * (indent + 4) + x if x else "")
            else:
                result.append(" " * indent + f"{kind} {expr}: pass")
            continue
        simple = transform_simple_line(raw)
        if simple is not None:
            result.append(" " * indent + simple)
        else:
            result.append(raw)
        i += 1
    return '\n'.join(result)

def transform_code(code):
    lines = code.replace('\t', '    ').splitlines()
    return transform_lines(lines)
# =========================
# Run in a softer way
# =========================
root = tk.Tk()
root.title("BlueStar IDE")
root.geometry("1000x700")
root.configure(bg="#111111")
top = tk.Frame(root, bg="#222222")
top.pack(fill=tk.X)
main_pane = tk.PanedWindow(root, orient=tk.VERTICAL, sashrelief=tk.RAISED, bg="#111111")
main_pane.pack(fill=tk.BOTH, expand=True)
editor_frame = tk.Frame(main_pane, bg="#111111")
output_frame = tk.Frame(main_pane, bg="#111111")
main_pane.add(editor_frame)
main_pane.add(output_frame)
tk.Label(editor_frame, text="BlueStar Code", bg="#111111", fg="white", anchor="w").pack(fill=tk.X)
editor = tk.Text(editor_frame, bg="#1e1e1e", fg="white", insertbackground="white", font=("Courier", 12))
editor.pack(fill=tk.BOTH, expand=True)
tk.Label(output_frame, text="Output", bg="#111111", fg="white", anchor="w").pack(fill=tk.X)
output = tk.Text(output_frame, bg="black", fg="lime", insertbackground="lime", font=("Courier", 12))
output.pack(fill=tk.BOTH, expand=True)
output.insert(tk.END, "BlueStar IDE Ready!\n")
output.insert(tk.END, "-" * 50 + "\n")
output.config(state="disabled")
run_thread = None
out_queue = queue.Queue()

def append_output(msg):
    output.config(state="normal")
    output.insert(tk.END, msg)
    output.see(tk.END)
    output.config(state="disabled")

def queue_writer(s):
    if s:
        out_queue.put(s)

class SoftStdout:
    def write(self, s):
        queue_writer(s)
        time.sleep(0.001)
    def flush(self):
        pass

def worker(code):
    transformed = transform_code(code)
    out_queue.put("--- Transformed Code ---\n")
    out_queue.put(transformed + "\n")
    out_queue.put("--- Output ---\n")
    old_stdout = sys.stdout
    sys.stdout = SoftStdout()
    try:
        exec(transformed, {"__builtins__": __builtins__}, {})
    except Exception as e:
        out_queue.put(f"error: {type(e).__name__}\n{e}\n")
    finally:
        sys.stdout = old_stdout
        out_queue.put("\n" + "-" * 50 + "\n")

def poll_queue():
    try:
        while True:
            msg = out_queue.get_nowait()
            append_output(msg)
    except queue.Empty:
        pass
    root.after(30, poll_queue)

def run_code():
    global run_thread
    if run_thread and run_thread.is_alive():
        messagebox.showwarning("Warning", "Code is already running!")
        return
    code = editor.get("1.0", tk.END).rstrip()
    if not code:
        return
    output.config(state="normal")
    output.delete("1.0", tk.END)
    output.config(state="disabled")
    run_thread = threading.Thread(target=worker, args=(code,), daemon=True)
    run_thread.start()

def save_file():
    code = editor.get("1.0", tk.END).rstrip()
    if not code:
        messagebox.showwarning("Warning", "No code to save!")
        return
    path = filedialog.asksaveasfilename(
        defaultextension=".bsat",
        filetypes=[("BlueStar Files", "*.bsat"), ("All Files", "*.*")]
    )
    if path:
        with open(path, "w", encoding="utf-8") as f:
            f.write(code)
        messagebox.showinfo("Success", f"Saved to {path}")

def load_file():
    path = filedialog.askopenfilename(
        filetypes=[("BlueStar Files", "*.bsat"), ("All Files", "*.*")]
    )
    if path:
        with open(path, "r", encoding="utf-8") as f:
            code = f.read()
        editor.delete("1.0", tk.END)
        editor.insert("1.0", code)

def clear_editor():
    editor.delete("1.0", tk.END)

tk.Button(top, text="RUN", bg="green", fg="white", command=run_code).pack(side=tk.LEFT, padx=5, pady=5)
tk.Button(top, text="SAVE", bg="#3498db", fg="white", command=save_file).pack(side=tk.LEFT, padx=5, pady=5)
tk.Button(top, text="LOAD", bg="#f39c12", fg="white", command=load_file).pack(side=tk.LEFT, padx=5, pady=5)
tk.Button(top, text="CLEAR", bg="red", fg="white", command=clear_editor).pack(side=tk.LEFT, padx=5, pady=5)
poll_queue()
output.config(state="disabled")
root.mainloop()