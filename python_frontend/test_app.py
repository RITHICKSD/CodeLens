from app import app, build_ast_branch_tree, estimate_space_complexity, estimate_time_complexity


def test_empty_code_returns_none():
    assert estimate_time_complexity("   \n\t  ") == "None"


def test_single_loop_returns_linear():
    code = """
for i in range(10):
    print(i)
"""
    assert estimate_time_complexity(code) == "O(n)"


def test_nested_loop_returns_quadratic():
    code = """
for i in range(10):
    for j in range(10):
        print(i, j)
"""
    assert estimate_time_complexity(code) == "O(n²)"


def test_recursive_fibonacci_complexity_uses_function_name():
    code = """def fibonacci(n):
    if n <= 1:
        return n
    return fibonacci(n - 1) + fibonacci(n - 2)
"""

    assert estimate_time_complexity(code) == "O(2^n)"
    assert estimate_space_complexity(code) == "O(n)"


def test_output_sure_is_no_for_syntax_error():
    client = app.test_client()
    response = client.post('/analyze', json={'code': 'if True print("broken")'})

    assert response.status_code == 200
    assert response.get_json()['metrics']['output_sure'] == 'No'


def test_output_sure_is_yes_for_clean_code():
    client = app.test_client()
    response = client.post('/analyze', json={'code': 'print("ready")'})

    assert response.status_code == 200
    assert response.get_json()['metrics']['output_sure'] == 'Yes'


def test_run_python_includes_time_complexity():
    client = app.test_client()
    response = client.post('/run-python', json={'code': 'for i in range(3):\n    print(i)'})

    assert response.status_code == 200
    payload = response.get_json()
    assert payload['status'] == 'success'
    assert payload['time_complexity'] == 'O(n)'


def test_run_python_includes_space_complexity():
    client = app.test_client()
    response = client.post('/run-python', json={'code': 'values = [1, 2, 3]\nprint(sum(values))'})

    assert response.status_code == 200
    payload = response.get_json()
    assert payload['status'] == 'success'
    assert payload['space_complexity'] == 'O(n)'


def test_output_sure_is_no_for_syntax_error():
    client = app.test_client()
    response = client.post('/analyze', json={'code': 'print('})

    assert response.get_json()['metrics']['output_sure'] == 'No'


def test_output_sure_is_no_for_detected_code_issue():
    client = app.test_client()
    response = client.post('/analyze', json={'code': 'for i in range(len(items)):\n    print(items[i])'})

    assert response.get_json()['metrics']['output_sure'] == 'No'


def test_hosted_demo_requires_access_code(monkeypatch):
    monkeypatch.setenv('DEMO_ACCESS_CODE', 'class-demo-code')
    client = app.test_client()

    denied = client.get('/')
    allowed = client.get('/', headers={'Authorization': 'Basic ZGVtbzpjbGFzcy1kZW1vLWNvZGU='})
    health = client.get('/healthz')

    assert denied.status_code == 401
    assert allowed.status_code == 200
    assert health.status_code == 200


def test_build_ast_branch_tree_creates_nested_structure():
    tree = build_ast_branch_tree(
        __import__('ast').parse('def greet(name):\n    print(name)')
    )

    assert tree['label'] == 'Module'
    assert tree['children']
    assert any(child['label'] == 'FunctionDef' for child in tree['children'])
    assert tree['children'][0]['children']
