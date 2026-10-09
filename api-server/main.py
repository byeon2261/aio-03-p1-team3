"""uv run fastapi dev main.py로 실행하는 통합 API 진입점."""

from app.factory import create_app

app = create_app()


# if __name__ == "__main__":
#     import uvicorn

#     uvicorn.run(app, host="127.0.0.1", port=8000)
