import httpx
from urllib.parse import urlencode

try:
    # 1. Login to get token
    r1 = httpx.post('http://localhost:8000/api/auth/login', 
        content=urlencode({'username': 'testuser', 'password': 'test1234'}),
        headers={'Content-Type': 'application/x-www-form-urlencoded'},
        timeout=5.0
    )
    token = r1.json().get('access_token')
    headers = {'Authorization': f'Bearer {token}'}

    # 2. Test GET /api/settings
    r_settings = httpx.get('http://localhost:8000/api/settings', headers=headers, timeout=5.0)
    print('GET /api/settings:', r_settings.status_code, r_settings.json())

    # 3. Test GET /api/settings/models
    r_models = httpx.get('http://localhost:8000/api/settings/models', headers=headers, timeout=5.0)
    print('GET /api/settings/models:', r_models.status_code, r_models.json())

    # 4. Test GET /api/settings/hardware
    r_hw = httpx.get('http://localhost:8000/api/settings/hardware', headers=headers, timeout=5.0)
    print('GET /api/settings/hardware:', r_hw.status_code, r_hw.json())

    # 5. Test create task
    r_task = httpx.post('http://localhost:8000/api/tasks', json={
        'title': 'Test Discovery',
        'description': 'Discover hidden game mechanics',
        'max_iterations': 50,
        'model': 'phi3:mini',
        'temperature': 0.7,
        'persistent_learning': False
    }, headers=headers, timeout=5.0)
    print('POST /api/tasks:', r_task.status_code, r_task.json().get('id'))

except Exception as e:
    print('Error:', type(e), e)
