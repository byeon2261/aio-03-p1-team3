# Backend

## 실행

`.env.example`을 `.env`로 복사한 뒤 Supabase 프로젝트의 API URL과 Publishable key를 입력한다.
`SUPABASE_URL`에는 `https://<project-ref>.supabase.co` 형식의 API 주소를 사용한다.
Redis 연결 주소는 `REDIS_URL`에 설정한다. 회원가입·로그인 요청은 Redis에 접속하지 않는다.

```powershell
cd api-server
uv sync
uv run fastapi dev main.py
```

`uv run python main.py`로도 실행할 수 있다. 서버 주소는 `http://127.0.0.1:8000`이다.
`.env`는 실행 디렉터리와 관계없이 `api-server/.env`에서 읽는다.

## 회원가입·로그인 확인

`http://127.0.0.1:8000/docs`에서 아래 API를 실행한다.


회원가입·로그인 요청 예시:

```json
{
  "email": "your-email@example.com",
  "password": "ExamplePass123!"
}
```

인증 회귀 테스트(외부 계정 생성 없이 SDK HTTP 응답을 대체):

```powershell
uv run pytest
```
