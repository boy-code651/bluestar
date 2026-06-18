import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import re
import sys
from io import StringIO
import threading
import queue
import time
from tkinter import font
import subprocess
import os
import tempfile

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
# Documentation Viewer
# =========================
class DocumentationViewer:
    def __init__(self, parent):
        self.window = None
        self.parent = parent
        
    def show_documentation(self):
        if self.window and self.window.winfo_exists():
            self.window.lift()
            return
            
        self.window = tk.Toplevel(self.parent)
        self.window.title("BlueStar Documentation")
        self.window.geometry("700x500")
        self.window.configure(bg="#1e1e1e")
        
        # Make it modal
        self.window.transient(self.parent)
        self.window.grab_set()
        
        # Header
        header = tk.Label(self.window, text="📚 BlueStar Language Documentation", 
                         font=("Segoe UI", 16, "bold"), bg="#1e1e1e", fg="#ffffff")
        header.pack(pady=10)
        
        # Create frame for documentation content
        doc_frame = tk.Frame(self.window, bg="#1e1e1e")
        doc_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        # Scrollbar for text
        scrollbar = tk.Scrollbar(doc_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Documentation text
        self.doc_text = tk.Text(doc_frame, bg="#2d2d2d", fg="#d4d4d4", 
                               font=("Courier", 11), wrap=tk.WORD,
                               yscrollcommand=scrollbar.set)
        self.doc_text.pack(fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.doc_text.yview)
        
        # Insert documentation
        self.insert_documentation()
        
        # Close button
        close_btn = tk.Button(self.window, text="Close", command=self.close_documentation,
                             bg="#e74c3c", fg="white", font=("Segoe UI", 10),
                             padx=20, pady=5, relief=tk.FLAT)
        close_btn.pack(pady=10)
        
    def insert_documentation(self):
        doc = """
═══════════════════════════════════════════════════════════
                BLUESTAR LANGUAGE DOCUMENTATION
═══════════════════════════════════════════════════════════

🔵 DATA TYPES
═══════════════════════════════════════════════════════════

📌 NUM (Number)
    Syntax: data num name(value)
    Example: data num age(25)
    Description: Defines a numeric variable

📌 STR (String)
    Syntax: data str name(value)
    Example: data str name("John")
    Description: Defines a string variable

📌 BOL (Boolean)
    Syntax: data bol name(true/false)
    Example: data bol isActive(true)
    Description: Defines a boolean variable

📌 DEAL (Boolean alternative)
    Syntax: data deal name(yes/no)
    Example: data deal isReady(yes)
    Description: Defines a boolean variable using yes/no

═══════════════════════════════════════════════════════════

🟢 VARIABLES
═══════════════════════════════════════════════════════════

📌 UPDATE
    Syntax: update var:name (type=type in=value)
    Example: update var:age (type=num in=25)
    Description: Updates an existing variable

📌 VAR (Variable Reference)
    Syntax: var:name
    Example: var:age
    Description: References an existing variable

═══════════════════════════════════════════════════════════

🟡 OUTPUT
═══════════════════════════════════════════════════════════

📌 SAY
    Syntax: say = value
    Example: say = "Hello World"
    Description: Prints output to console

═══════════════════════════════════════════════════════════

🔴 CONTROL FLOW
═══════════════════════════════════════════════════════════

📌 IF
    Syntax: if condition /
        code
    Example: 
        if age >= 18 /
            say = "Adult"
    Description: Conditional execution

📌 WHILE
    Syntax: while condition /
        code
    Example:
        while count < 10 /
            say = count
            update var:count (type=num in=count + 1)
    Description: Loop execution while condition is true

═══════════════════════════════════════════════════════════

🔵 COMMENTS
═══════════════════════════════════════════════════════════

📌 COM
    Syntax: com=comment text
    Example: com=This is a comment
    Description: Single line comment

═══════════════════════════════════════════════════════════

📊 COMPARISON OPERATORS
═══════════════════════════════════════════════════════════

    ==    Equal to
    !=    Not equal to
    >     Greater than
    <     Less than
    >=    Greater than or equal to
    <=    Less than or equal to

═══════════════════════════════════════════════════════════

💡 BOOLEAN VALUES
═══════════════════════════════════════════════════════════

    true  or  yes   → True
    false or  no    → False

═══════════════════════════════════════════════════════════

📝 EXAMPLE CODE
═══════════════════════════════════════════════════════════

    com=Define variables
    data num age(18)
    data str name("Alice")
    data bol isStudent(true)
    
    com=Update variable
    update var:age (type=num in=age + 1)
    
    com=Conditional
    if age >= 18 /
        say = name
        say = "is adult"
    
    com=Loop
    data num counter(0)
    while counter < 5 /
        say = counter
        update var:counter (type=num in=counter + 1)

═══════════════════════════════════════════════════════════
        """
        self.doc_text.insert(tk.END, doc)
        self.doc_text.config(state="disabled")
        
    def close_documentation(self):
        if self.window:
            self.window.destroy()
            self.window = None

# =========================
# Build Manager
# =========================
class BuildManager:
    def __init__(self, editor_widget, output_widget):
        self.editor = editor_widget
        self.output = output_widget
        self.temp_dir = tempfile.gettempdir()
        
    def build_exe(self):
        code = self.editor.get("1.0", tk.END).rstrip()
        if not code:
            messagebox.showwarning("Warning", "No code to build!")
            return
            
        # Transform code
        transformed = transform_code(code)
        
        # Create temporary Python file
        temp_file = os.path.join(self.temp_dir, "bluestar_temp.py")
        with open(temp_file, "w", encoding="utf-8") as f:
            f.write(transformed)
            
        # Ask for output location
        output_path = filedialog.asksaveasfilename(
            defaultextension=".exe",
            filetypes=[("Executable Files", "*.exe"), ("All Files", "*.*")],
            title="Save Executable As"
        )
        
        if not output_path:
            os.remove(temp_file)
            return
            
        try:
            # Build using PyInstaller
            self.append_output("Building executable...\n")
            self.append_output("-" * 50 + "\n")
            
            # Create spec file
            spec_content = f"""
# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ['{temp_file}'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={{}},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='{os.path.splitext(os.path.basename(output_path))[0]}',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    cofile=None,
    icon=None,
)
"""
            spec_file = os.path.join(self.temp_dir, "bluestar.spec")
            with open(spec_file, "w", encoding="utf-8") as f:
                f.write(spec_content)
                
            # Build using PyInstaller
            cmd = [sys.executable, "-m", "PyInstaller", "--distpath", os.path.dirname(output_path), spec_file]
            
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=self.temp_dir
            )
            
            # Read output in real-time
            while True:
                output_line = process.stdout.readline()
                if output_line == '' and process.poll() is not None:
                    break
                if output_line:
                    self.append_output(output_line)
                    
            # Read stderr
            stderr_output = process.stderr.read()
            if stderr_output:
                self.append_output(stderr_output)
                
            if process.returncode == 0:
                self.append_output("\n" + "-" * 50 + "\n")
                self.append_output(f"✅ Build successful! Executable saved to:\n{output_path}\n")
                messagebox.showinfo("Success", f"Build successful!\nExecutable saved to:\n{output_path}")
            else:
                self.append_output("\n" + "-" * 50 + "\n")
                self.append_output(f"❌ Build failed with error code: {process.returncode}\n")
                messagebox.showerror("Build Failed", f"Build failed with error code: {process.returncode}")
                
        except Exception as e:
            self.append_output(f"Error during build: {str(e)}\n")
            messagebox.showerror("Build Error", f"Error during build:\n{str(e)}")
            
        finally:
            # Cleanup temporary files
            try:
                if os.path.exists(temp_file):
                    os.remove(temp_file)
                if os.path.exists(spec_file):
                    os.remove(spec_file)
            except:
                pass
                
    def append_output(self, msg):
        self.output.config(state="normal")
        self.output.insert(tk.END, msg)
        self.output.see(tk.END)
        self.output.config(state="disabled")

# =========================
# Theme Manager
# =========================
class ThemeManager:
    def __init__(self):
        self.themes = {
            "dark": {
                "bg": "#1e1e1e",
                "fg": "#d4d4d4",
                "selectbg": "#264f78",
                "selectfg": "#ffffff",
                "insertbg": "#ffffff",
                "output_bg": "#1e1e1e",
                "output_fg": "#00ff00",
                "button_bg": "#007acc",
                "button_fg": "#ffffff",
                "root_bg": "#111111",
                "top_bg": "#222222",
                "pane_bg": "#111111",
                "frame_bg": "#111111",
                "label_fg": "white"
            },
            "light": {
                "bg": "#ffffff",
                "fg": "#000000",
                "selectbg": "#c7e0f4",
                "selectfg": "#000000",
                "insertbg": "#000000",
                "output_bg": "#ffffff",
                "output_fg": "#006600",
                "button_bg": "#007acc",
                "button_fg": "#ffffff",
                "root_bg": "#f0f0f0",
                "top_bg": "#e0e0e0",
                "pane_bg": "#f0f0f0",
                "frame_bg": "#f0f0f0",
                "label_fg": "black"
            }
        }
        self.current_theme = "dark"
        
    def apply_theme(self, widget, theme):
        if hasattr(widget, 'tk'):
            widget.configure(bg=theme["bg"], fg=theme["fg"])
            
    def get_theme(self, name=None):
        if name is None:
            name = self.current_theme
        return self.themes.get(name, self.themes["dark"])

# =========================
# Main Application
# =========================
root = tk.Tk()
root.title("BlueStar IDE")
root.geometry("1000x700")

theme_manager = ThemeManager()
current_theme = theme_manager.get_theme()

# Configure root
root.configure(bg=current_theme["root_bg"])

top = tk.Frame(root, bg=current_theme["top_bg"])
top.pack(fill=tk.X)

main_pane = tk.PanedWindow(root, orient=tk.VERTICAL, sashrelief=tk.RAISED, 
                          bg=current_theme["pane_bg"])
main_pane.pack(fill=tk.BOTH, expand=True)

editor_frame = tk.Frame(main_pane, bg=current_theme["frame_bg"])
output_frame = tk.Frame(main_pane, bg=current_theme["frame_bg"])
main_pane.add(editor_frame)
main_pane.add(output_frame)

tk.Label(editor_frame, text="BlueStar Code", bg=current_theme["frame_bg"], 
         fg=current_theme["label_fg"], anchor="w").pack(fill=tk.X)

# Editor with scrollbar
editor_frame_inner = tk.Frame(editor_frame, bg=current_theme["frame_bg"])
editor_frame_inner.pack(fill=tk.BOTH, expand=True)

editor_scrollbar = tk.Scrollbar(editor_frame_inner)
editor_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

editor = tk.Text(editor_frame_inner, bg=current_theme["bg"], fg=current_theme["fg"], 
                insertbackground=current_theme["insertbg"], font=("Courier", 12),
                yscrollcommand=editor_scrollbar.set)
editor.pack(fill=tk.BOTH, expand=True)
editor_scrollbar.config(command=editor.yview)

tk.Label(output_frame, text="Output", bg=current_theme["frame_bg"], 
         fg=current_theme["label_fg"], anchor="w").pack(fill=tk.X)

# Output with scrollbar
output_frame_inner = tk.Frame(output_frame, bg=current_theme["frame_bg"])
output_frame_inner.pack(fill=tk.BOTH, expand=True)

output_scrollbar = tk.Scrollbar(output_frame_inner)
output_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

output = tk.Text(output_frame_inner, bg=current_theme["output_bg"], fg=current_theme["output_fg"],
                insertbackground=current_theme["insertbg"], font=("Courier", 12),
                yscrollcommand=output_scrollbar.set)
output.pack(fill=tk.BOTH, expand=True)
output_scrollbar.config(command=output.yview)

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

def toggle_theme():
    if theme_manager.current_theme == "dark":
        theme_manager.current_theme = "light"
        new_theme = theme_manager.get_theme()
        root.configure(bg=new_theme["root_bg"])
        top.configure(bg=new_theme["top_bg"])
        main_pane.configure(bg=new_theme["pane_bg"])
        editor_frame.configure(bg=new_theme["frame_bg"])
        output_frame.configure(bg=new_theme["frame_bg"])
        
        # Update editor
        editor.configure(bg=new_theme["bg"], fg=new_theme["fg"], 
                        insertbackground=new_theme["insertbg"])
        
        # Update output
        output.configure(bg=new_theme["output_bg"], fg=new_theme["output_fg"])
        
        # Update labels
        for child in editor_frame.winfo_children():
            if isinstance(child, tk.Label):
                child.configure(bg=new_theme["frame_bg"], fg=new_theme["label_fg"])
        for child in output_frame.winfo_children():
            if isinstance(child, tk.Label):
                child.configure(bg=new_theme["frame_bg"], fg=new_theme["label_fg"])
        
        # Update status bar
        status_bar.configure(bg="#e0e0e0", fg="black")
                
    else:
        theme_manager.current_theme = "dark"
        new_theme = theme_manager.get_theme()
        root.configure(bg=new_theme["root_bg"])
        top.configure(bg=new_theme["top_bg"])
        main_pane.configure(bg=new_theme["pane_bg"])
        editor_frame.configure(bg=new_theme["frame_bg"])
        output_frame.configure(bg=new_theme["frame_bg"])
        
        # Update editor
        editor.configure(bg=new_theme["bg"], fg=new_theme["fg"], 
                        insertbackground=new_theme["insertbg"])
        
        # Update output
        output.configure(bg=new_theme["output_bg"], fg=new_theme["output_fg"])
        
        # Update labels
        for child in editor_frame.winfo_children():
            if isinstance(child, tk.Label):
                child.configure(bg=new_theme["frame_bg"], fg=new_theme["label_fg"])
        for child in output_frame.winfo_children():
            if isinstance(child, tk.Label):
                child.configure(bg=new_theme["frame_bg"], fg=new_theme["label_fg"])
        
        # Update status bar
        status_bar.configure(bg="#2d2d2d", fg="white")

# Button icons (using unicode characters as simple icons)
def create_button(parent, text, icon, command, bg_color, fg_color="#ffffff"):
    btn = tk.Button(parent, text=f"{icon} {text}", bg=bg_color, fg=fg_color, 
                   font=("Segoe UI", 10, "bold"), command=command,
                   padx=10, pady=5, relief=tk.FLAT, cursor="hand2")
    btn.pack(side=tk.LEFT, padx=5, pady=5)
    return btn

# Build manager
build_manager = BuildManager(editor, output)

# Documentation viewer
doc_viewer = DocumentationViewer(root)

# Theme toggle button
theme_btn = tk.Button(top, text="🌓 Dark/Light", bg="#6c3483", fg="white",
                     font=("Segoe UI", 10, "bold"), command=toggle_theme,
                     padx=10, pady=5, relief=tk.FLAT, cursor="hand2")
theme_btn.pack(side=tk.RIGHT, padx=5, pady=5)

# Buttons with icons
create_button(top, "Run", "▶", run_code, "#27ae60")
create_button(top, "Save", "💾", save_file, "#2980b9")
create_button(top, "Load", "📂", load_file, "#f39c12")
create_button(top, "Clear", "🗑", clear_editor, "#e74c3c")
create_button(top, "Build", "🏗️", build_manager.build_exe, "#8e44ad")
create_button(top, "Doc", "📚", doc_viewer.show_documentation, "#2c3e50")

# Status bar
status_bar = tk.Label(root, text="Ready", bd=1, relief=tk.SUNKEN, anchor=tk.W,
                     bg="#2d2d2d" if current_theme["bg"] == "#1e1e1e" else "#e0e0e0",
                     fg="white" if current_theme["bg"] == "#1e1e1e" else "black")
status_bar.pack(side=tk.BOTTOM, fill=tk.X)

# Update status bar on editor changes
def update_status(event=None):
    cursor_pos = editor.index(tk.INSERT)
    line, col = cursor_pos.split('.')
    status_bar.config(text=f"Line: {line} | Column: {int(col)+1}")

editor.bind('<KeyRelease>', update_status)
editor.bind('<ButtonRelease-1>', update_status)

poll_queue()
output.config(state="disabled")
root.mainloop()
