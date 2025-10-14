FROM python:3.13-slim

# 作業ディレクトリを設定
WORKDIR /app

# システムの依存関係をインストール
RUN apt-get update && apt-get install -y \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# uvをインストール
RUN pip install uv

# プロジェクトファイルをコピー
# 最初に依存関係ファイルのみをコピーしてレイヤーキャッシュを最適化
COPY pyproject.toml uv.lock ./

# uvを使用して依存関係をインストール
# --frozenオプションでuv.lockファイルを厳密に使用
RUN uv sync --frozen

# アプリケーションのソースコードをコピー
COPY . .

# データベースファイル用のディレクトリを作成
RUN mkdir -p /app/data

# uvを使用してアプリケーションを実行
CMD ["uv", "run", "./lib/declarate.py"]
CMD ["uv", "run", "main.py"]
