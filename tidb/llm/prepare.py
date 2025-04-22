# -*- coding: utf-8 -*-

import os
import requests
from bs4 import BeautifulSoup
from sqlalchemy import URL, create_engine, text
from llama_index.core import (
    VectorStoreIndex,
    StorageContext,
    Document
)
from llama_index.core.settings import Settings
from llama_index.llms.bedrock_converse import BedrockConverse
from llama_index.vector_stores.tidbvector import TiDBVectorStore
from llama_index.embeddings.bedrock import BedrockEmbedding
from dotenv import load_dotenv

load_dotenv()
tidb_username = os.environ['TIDB_USERNAME']
tidb_password = os.environ['TIDB_PASSWORD']
tidb_host = os.environ['TIDB_HOSTNAME']
tidb_database = os.environ['TIDB_DATABASE_NAME']

# LlamaIndex - Amazon Bedrock
llm = BedrockConverse(model="anthropic.claude-3-sonnet-20240229-v1:0")
embed_model = BedrockEmbedding(model="amazon.titan-embed-text-v2:0")

Settings.llm = llm
Settings.embed_model = embed_model

def get_webpage_content(urls):
    documents = []
    for url in urls:
        response = requests.get(url)
        response.encoding = 'utf-8'
        soup = BeautifulSoup(response.text, 'html.parser')
        text = soup.get_text(separator=' ', strip=True)

        # エンコーディングを確認
        text = text.encode('utf-8').decode('utf-8')

        documents.append(Document(
            text=text,
            metadata={'source': url}
        ))
    return documents

def main():
    # TiDB Cloud Serverless 用の接続文字列
    connection_url = f"mysql+pymysql://{tidb_username}:{tidb_password}@{tidb_host}:4000/{tidb_database}?ssl_verify_cert=true&ssl_verify_identity=true&charset=utf8mb4"

    # TiDBVectorStore の初期化
    tidbvec = TiDBVectorStore(
        connection_string=connection_url,
        table_name="llama_index_rag",
        distance_strategy="cosine",
        vector_dimension=1536,
        drop_existing_table=False
    )

    documents = get_webpage_content([
        "https://docs.pingcap.com/ja/tidb/stable/overview",
        "https://docs.pingcap.com/ja/tidb/stable/release-7.5.0",
        "https://docs.pingcap.com/ja/tidb/stable/mysql-compatibility",
        "https://docs.pingcap.com/ja/tidbcloud/tidb-cloud-intro#architecture"
    ])

    # データを挿入する前にテキストのエンコーディングを確認
    for doc in documents:
        print("Document encoding check:", doc.text[:100])

    storage_context = StorageContext.from_defaults(vector_store=tidbvec)
    tidb_vec_index = VectorStoreIndex.from_vector_store(tidbvec)
    tidb_vec_index.from_documents(documents, storage_context=storage_context, show_progress=True)

    # データ挿入後の確認
    # SQLAlchemy エンジンを作成
    engine = create_engine(connection_url)

    with engine.connect() as connection:
        result = connection.execute(text("SELECT document FROM llama_index_rag LIMIT 1"))
        retrieved_text = result.fetchone()[0]
        print("\nRetrieved text from database:", retrieved_text[:200])

    return tidb_vec_index

if __name__ == "__main__":
    main()
