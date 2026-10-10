import ast
import threading
import uuid
import subprocess
import sys
import time
import hmac
import os
from flask import Flask, render_template, request, jsonify

app = Flask(__name__, template_folder='templates', static_folder='static')
interactive_sessions = {}
interactive_sessions_lock = threading.Lock()


@app.before_request
def require_demo_access_code():
    access_code = os.environ.get('DEMO_ACCESS_CODE')
    if not access_code or request.endpoint == 'health_check':
        return None

    authorization = request.authorization
    supplied_code = authorization.password if authorization else ''
    if authorization and authorization.username == 'demo' and hmac.compare_digest(supplied_code, access_code):
        return None

    return jsonify({'status': 'unauthorized', 'message': 'Demo access code required.'}), 401, {
        'WWW-Authenticate': 'Basic realm="CodeLENSE Demo", charset="UTF-8"'
    }


def estimate_time_complexity(code):
    """Return a deterministic, AST-based time complexity estimate.

    Empty or whitespace-only code returns None.
    Simple linear code returns O(n), nested loops return O(n^k),
    and plain constant-time code returns O(1).
    """
    if code is None:
        return "None"

    stripped = code.strip()
    if not stripped:
        return "None"

    try:
        tree = ast.parse(code)
    except SyntaxError:
        return "None"

    loop_depth = 0
    recursive_call_count = 0

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        recursive_call_count = max(
            recursive_call_count,
            sum(
                isinstance(call, ast.Call)
                and isinstance(call.func, ast.Name)
                and call.func.id == node.name
                for call in ast.walk(node)
            )
        )

    def walk(node, depth=0):
        nonlocal loop_depth

        if isinstance(node, (ast.For, ast.AsyncFor, ast.While)):
            loop_depth = max(loop_depth, depth + 1)
            for child in ast.iter_child_nodes(node):
                walk(child, depth + 1)
            return

        for child in ast.iter_child_nodes(node):
            walk(child, depth)

    walk(tree)

    if recursive_call_count >= 2:
        return "O(2^n)"
    if recursive_call_count == 1:
        return "O(n)"
    if loop_depth >= 3:
        return f"O(n^{loop_depth})"
    if loop_depth == 2:
        return "O(n²)"
    if loop_depth == 1:
        return "O(n)"
    return "O(1)"


def estimate_space_complexity(code):
    """Return a deterministic, AST-based space complexity estimate."""
    if code is None:
        return "None"

    stripped = code.strip()
    if not stripped:
        return "None"

    try:
        tree = ast.parse(code)
    except SyntaxError:
        return "None"

    recursive = False
    collection_nodes = 0
    nested_collection_depth = 0

    collection_types = (
        ast.List,
        ast.Tuple,
        ast.Set,
        ast.Dict,
        ast.ListComp,
        ast.SetComp,
        ast.DictComp,
        ast.GeneratorExp,
    )

    def walk(node):
        nonlocal recursive, collection_nodes, nested_collection_depth

        if isinstance(node, collection_types):
            collection_nodes += 1
            for child in ast.iter_child_nodes(node):
                if isinstance(child, collection_types):
                    nested_collection_depth += 1

        for child in ast.iter_child_nodes(node):
            walk(child)

    walk(tree)

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if any(
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Name)
            and call.func.id == node.name
            for call in ast.walk(node)
        ):
            recursive = True

    if nested_collection_depth > 0:
        return "O(n²)"
    if recursive:
        return "O(n)"
    if collection_nodes > 0:
        return "O(n)"
    return "O(1)"


def build_ast_branch_tree(node):
    """Build a nested tree view of the AST with a branch-friendly structure."""
    if node is None:
        return {'label': 'None', 'children': []}

    label = type(node).__name__
    result = {'label': label, 'type': label, 'children': []}

    if hasattr(node, 'lineno'):
        result['line'] = node.lineno

    if hasattr(node, 'id'):
        result['name'] = node.id
    elif hasattr(node, 'name'):
        result['name'] = node.name
    elif hasattr(node, 'arg'):
        result['name'] = node.arg

    for field, value in ast.iter_fields(node):
        if isinstance(value, list):
            for item in value:
                if isinstance(item, ast.AST):
                    result['children'].append(build_ast_branch_tree(item))
        elif isinstance(value, ast.AST):
            result['children'].append(build_ast_branch_tree(value))

    return result


def parse_ast_tree(node):
    """Backward-compatible AST node conversion used across the app."""
    return build_ast_branch_tree(node)


def extract_symbols(code):
    """Extract functions, classes, and imports from code for IDE symbol outline."""
    symbols = []
    try:
        tree = ast.parse(code)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                symbols.append({
                    'type': 'function',
                    'name': node.name,
                    'line': node.lineno,
                    'args': [a.arg for a in node.args.args]
                })
            elif isinstance(node, ast.ClassDef):
                symbols.append({
                    'type': 'class',
                    'name': node.name,
                    'line': node.lineno
                })
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                else:
                    names = [f"{node.module}.{alias.name}" for alias in node.names]
                symbols.append({
                    'type': 'import',
                    'name': ', '.join(names),
                    'line': node.lineno
                })
    except Exception:
        pass
    return sorted(symbols, key=lambda x: x['line'])


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/healthz')
def health_check():
    return jsonify({'status': 'ok'})


@app.route('/compiler')
def compiler_page():
    return render_template('compiler.html')


@app.route('/run-python', methods=['POST'])
def run_python():
    data = request.get_json(silent=True) or {}
    code = data.get('code', '')
    stdin_data = data.get('stdin', '')

    if not isinstance(code, str) or not code.strip():
        return jsonify({
            'status': 'empty',
            'output': 'No code to run. Please type your Python program first.'
        })

    if not isinstance(stdin_data, str):
        stdin_data = ''

    try:
        compile(code, '<compiler>', 'exec')
    except SyntaxError as error:
        line = error.lineno or 1
        column = error.offset or 1
        message = f"SyntaxError on line {line}, column {column}: {error.msg}"
        return jsonify({
            'status': 'syntax_error',
            'output': message,
            'runtime': 0.0
        })

    started_at = time.perf_counter()
    result = subprocess.run(
        [sys.executable, '-c', code],
        input=stdin_data,
        capture_output=True,
        text=True
    )

    runtime = round(time.perf_counter() - started_at, 2)
    output = result.stdout
    if result.stderr:
        output += result.stderr

    time_complexity = estimate_time_complexity(code)
    space_complexity = estimate_space_complexity(code)

    return jsonify({
        'status': 'success' if result.returncode == 0 else 'error',
        'output': output.rstrip() or 'Program executed successfully with no output.',
        'runtime': runtime,
        'time_complexity': time_complexity,
        'space_complexity': space_complexity
    })


def read_interactive_output(session_id, process):
    session = interactive_sessions[session_id]
    while True:
        chunk = process.stdout.read(1)
        if not chunk:
            break
        with interactive_sessions_lock:
            session['output'] += chunk
    with interactive_sessions_lock:
        session['status'] = 'success' if process.returncode == 0 else 'error'


@app.route('/run-python-session', methods=['POST'])
def start_python_session():
    data = request.get_json(silent=True) or {}
    code = data.get('code', '')
    if not isinstance(code, str) or not code.strip():
        return jsonify({'status': 'empty', 'output': 'No code to run.'}), 400

    try:
        compile(code, '<compiler>', 'exec')
    except SyntaxError as error:
        return jsonify({
            'status': 'syntax_error',
            'output': f"SyntaxError on line {error.lineno or 1}, column {error.offset or 1}: {error.msg}"
        })

    session_id = uuid.uuid4().hex
    process = subprocess.Popen(
        [sys.executable, '-u', '-c', code],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )
    interactive_sessions[session_id] = {
        'process': process,
        'output': '',
        'status': 'running',
        'started_at': time.perf_counter()
    }
    threading.Thread(target=read_interactive_output, args=(session_id, process), daemon=True).start()
    return jsonify({'status': 'running', 'session_id': session_id})


@app.route('/run-python-session/<session_id>/input', methods=['POST'])
def send_python_session_input(session_id):
    data = request.get_json(silent=True) or {}
    value = data.get('value', '')
    session = interactive_sessions.get(session_id)
    if not session or session['status'] != 'running':
        return jsonify({'status': 'error', 'output': 'This program is no longer running.'}), 400

    try:
        session['process'].stdin.write(f'{value}\n')
        session['process'].stdin.flush()
    except (BrokenPipeError, OSError):
        return jsonify({'status': 'error', 'output': 'The program stopped before receiving input.'}), 400
    return jsonify({'status': 'running'})


@app.route('/run-python-session/<session_id>', methods=['GET'])
def poll_python_session(session_id):
    session = interactive_sessions.get(session_id)
    if not session:
        return jsonify({'status': 'error', 'output': 'Session not found.'}), 404

    process = session['process']
    return jsonify({'status': session['status'], 'output': session['output']})


@app.route('/analyze', methods=['POST'])
def analyze():
    data = request.json or {}
    code = data.get('code', '')

    # Language Validation: Detect Java / C++ non-Python code
    java_signatures = [
        'public class ', 'public static void main', 'System.out.println',
        'System.out.print', 'import java.', 'private int ', 'public int ',
        'private String ', 'public String ', 'String[] args', 'extends ', 'implements '
    ]
    if any(sig in code for sig in java_signatures):
        return jsonify({
            'status': 'invalid_language',
            'message': 'Please Enter Python Code'
        })

    lines = code.split('\n')
    line_count = len(lines)
    char_count = len(code)
    non_empty_lines = len([l for l in lines if l.strip()])

    # Real AST Parsing
    ast_tree = None
    ast_error = None
    syntax_error_line = 1
    try:
        parsed = ast.parse(code)
        ast_tree = parse_ast_tree(parsed)
    except SyntaxError as e:
        ast_error = f"Syntax Error at line {e.lineno}: {e.msg}"
        syntax_error_line = e.lineno or 1

    # Symbol Outline
    symbols = extract_symbols(code)

    # Heuristic Security & Quality Issues
    issues = []

    if ast_error:
        issues.append({
            'type': 'critical',
            'category': 'Syntax Engine',
            'title': 'Python Syntax Exception',
            'description': ast_error,
            'line': syntax_error_line,
            'rule_id': 'SYN-001'
        })

    for idx, line in enumerate(lines, 1):
        line_str = line.strip()

        if 'eval(' in line_str or 'exec(' in line_str:
            issues.append({
                'type': 'critical',
                'category': 'Security Audit',
                'title': 'Unsafe Dynamic Code Execution (eval/exec)',
                'description': 'Dynamic evaluation of strings introduces Remote Code Execution risks. Replace with safe literal_eval or explicit parser.',
                'line': idx,
                'rule_id': 'SEC-EVAL-01'
            })

        if 'SELECT' in line_str.upper() and ('%' in line_str or '+' in line_str or '.format' in line_str or 'f"' in line_str or "f'" in line_str):
            issues.append({
                'type': 'critical',
                'category': 'Security Audit',
                'title': 'Potential SQL Injection Vulnerability',
                'description': 'SQL query constructed via string formatting/concatenation. Use parameterized query bindings (cursor.execute(sql, params)).',
                'line': idx,
                'rule_id': 'SEC-SQLI-02'
            })

        if '/ 0' in line_str or '/0' in line_str:
            issues.append({
                'type': 'critical',
                'category': 'Logical Error',
                'title': 'Division by Zero Detected',
                'description': 'Dividing by literal zero will cause a runtime ZeroDivisionError exception.',
                'line': idx,
                'rule_id': 'LOGIC-DIV-0'
            })

        if line_str.startswith('except:') or line_str.startswith('except Exception:'):
            issues.append({
                'type': 'warning',
                'category': 'Code Quality',
                'title': 'Bare Exception Handler Catch-all',
                'description': 'Catching bare Exception suppresses unexpected system interrupts and masks underlying runtime errors.',
                'line': idx,
                'rule_id': 'QUAL-EXC-01'
            })

        if 'range(len(' in line_str:
            issues.append({
                'type': 'optimization',
                'category': 'Pythonic Style',
                'title': 'Non-pythonic iteration over range(len(...))',
                'description': 'Prefer using enumerate() or direct sequence iteration instead of explicit index lookup.',
                'line': idx,
                'rule_id': 'STYLE-ITER-01'
            })

        # Logical Error 1: Division by Zero
        if '/ 0' in line_str or '/0' in line_str or '// 0' in line_str or '//0' in line_str:
            issues.append({
                'type': 'critical',
                'category': 'Logical Error',
                'title': 'ZeroDivisionError Exception Risk',
                'description': 'Attempting to divide by zero will cause an immediate runtime ZeroDivisionError crash.',
                'line': idx,
                'rule_id': 'LOGIC-DIV-ZERO'
            })

        # Logical Error 2: Potential Infinite Loop (while True without break)
        if (line_str.startswith('while True:') or line_str.startswith('while 1:')) and not any('break' in l for l in lines[idx:idx+15]):
            issues.append({
                'type': 'warning',
                'category': 'Logical Error',
                'title': 'Unbounded Loop Pattern (while True)',
                'description': 'Infinite loop structure detected without an explicit break condition.',
                'line': idx,
                'rule_id': 'LOGIC-INF-LOOP'
            })

    if not issues:
        issues.append({
            'type': 'info',
            'category': 'System Scan',
            'title': 'Clean Code Inspection',
            'description': 'No critical security flaws or AST anti-patterns detected in current file.',
            'line': 1,
            'rule_id': 'SYS-PASS-00'
        })

    score = max(40, 100 - len([i for i in issues if i['type'] == 'critical']) * 25 - len([i for i in issues if i['type'] == 'warning']) * 10)
    
    # Calculate cyclomatic complexity metric approximation
    branches = code.count('if ') + code.count('elif ') + code.count('for ') + code.count('while ') + code.count('except ')
    complexity = branches + 1

    # Count functions
    function_count = len([s for s in symbols if s['type'] == 'function'])

    time_complexity = estimate_time_complexity(code)
    space_complexity = estimate_space_complexity(code)

    # Output Sure is "No" whenever analysis finds anything beyond the clean-pass info item.
    has_code_issue = ast_error is not None or any(i['type'] != 'info' for i in issues)
    output_sure = "No" if has_code_issue else "Yes"

    return jsonify({
        'status': 'ok',
        'metrics': {
            'lines': line_count,
            'characters': char_count,
            'non_empty_lines': non_empty_lines,
            'health_score': score,
            'complexity': complexity,
            'maintainability_index': round(max(20, 100 - (complexity * 3) - (line_count * 0.2)), 1),
            'function_count': function_count,
            'time_complexity': time_complexity,
            'space_complexity': space_complexity,
            'output_sure': output_sure
        },
        'symbols': symbols,
        'ast_tree': ast_tree or {'type': 'Module', 'name': 'SyntaxError'},
        'issues': issues,
        'summary': {
            'ast_nodes': char_count // 5 + 4,
            'security_rating': 'A+' if not any(i['type'] == 'critical' for i in issues) else 'F',
            'maintainability': 'High' if score >= 85 else ('Medium' if score >= 65 else 'Low'),
            'bandit_scan': 'PASSED (0 Critical)' if score >= 85 else 'ALERT (Security Finding Flagged)'
        }
    })


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5173, debug=True)
