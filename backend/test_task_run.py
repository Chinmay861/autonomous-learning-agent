import asyncio
import httpx
from urllib.parse import urlencode

async def run_test():
    async with httpx.AsyncClient(timeout=15.0) as client:
        # 1. Login
        r = await client.post('http://localhost:8000/api/auth/login', 
            content=urlencode({'username': 'testuser', 'password': 'test1234'}),
            headers={'Content-Type': 'application/x-www-form-urlencoded'}
        )
        token = r.json().get('access_token')
        headers = {'Authorization': f'Bearer {token}'}

        # 2. Create task (1 iteration test)
        task_data = {
            'title': 'Test 1-Iter Run',
            'description': 'Discover hidden rules in benchmark environment',
            'max_iterations': 2,
            'model': 'phi3:mini',
            'temperature': 0.7,
            'persistent_learning': False
        }
        res = await client.post('http://localhost:8000/api/tasks', json=task_data, headers=headers)
        task = res.json()
        task_id = task['id']
        print(f"Created task: {task_id}")

        # 3. Start task
        start_res = await client.post(f'http://localhost:8000/api/tasks/{task_id}/start', headers=headers)
        print(f"Start response: {start_res.json()}")

        # 4. Poll status for up to 60s
        for i in range(12):
            await asyncio.sleep(5)
            t_res = await client.get(f'http://localhost:8000/api/tasks/{task_id}', headers=headers)
            current = t_res.json()
            print(f"[{i*5}s] Task status: {current.get('status')} | Iteration: {current.get('current_iteration')}")
            if current.get('status') in ('COMPLETED', 'FAILED'):
                break

        # 5. Check iterations
        iters = await client.get(f'http://localhost:8000/api/tasks/{task_id}/iterations', headers=headers)
        print(f"Iterations recorded: {len(iters.json())}")

if __name__ == '__main__':
    asyncio.run(run_test())
