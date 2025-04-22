# -*- coding: utf-8 -*-

import logging
import sys
import streamlit as st
from sqlalchemy import URL
from llama_index.core import VectorStoreIndex
from llama_index.core.settings import Settings
# from llama_index.llms.bedrock import Bedrock
from llama_index.llms.bedrock_converse import BedrockConverse
from llama_index.vector_stores.tidbvector import TiDBVectorStore
from llama_index.embeddings.bedrock import BedrockEmbedding
import os
from dotenv import load_dotenv
logging.basicConfig(stream=sys.stdout, level=logging.INFO)
logger = logging.getLogger()

# .envファイルの内容を読み込見込む
load_dotenv()
tidb_username=os.environ['TIDB_USERNAME']
tidb_password=os.environ['TIDB_PASSWORD']
tidb_host=os.environ['TIDB_HOSTNAME']
tidb_database=os.environ['TIDB_DATABASE_NAME']

# ------------------------------------------------------------------------
# LlamaIndex - Amazon Bedrock
#llm = Bedrock(model="anthropic.claude-3-sonnet-20240229-v1:0")
llm = BedrockConverse(model="anthropic.claude-3-sonnet-20240229-v1:0")
embed_model = BedrockEmbedding(model="amazon.titan-embed-text-v2:0")

Settings.llm = llm
Settings.embed_model = embed_model

# Initialize TiDB Vector Store
if 'tidb_vec_index' not in st.session_state:
    tidb_connection_url = URL(
        "mysql+pymysql",
        username=tidb_username,
        password=tidb_password,
        host=tidb_host,
        port=4000,
        database=tidb_database,
        query={"ssl_verify_cert": True, "ssl_verify_identity": True},
    )

    tidbvec = TiDBVectorStore(
        connection_string=tidb_connection_url,
        table_name="llama_index_rag",
        distance_strategy="cosine",
        vector_dimension=1536,
        drop_existing_table=False,
    )

    tidb_vec_index = VectorStoreIndex.from_vector_store(tidbvec)
    st.session_state['tidb_vec_index'] = tidb_vec_index

query_engine = st.session_state['tidb_vec_index'].as_query_engine(streaming=True)

# ------------------------------------------------------------------------
# Streamlit

# Page title
st.set_page_config(page_title='TiDB & TiDB RAG DEMO')

# Clear Chat History function
def clear_screen():
    st.session_state.messages = [{"role": "assistant", "content": "TiDBのことについて学習しています。色々聞いてみてね！"}]

with st.sidebar:
    st.title('TiDBとBedrockを使ったRAGアプリケーション')
    st.divider()
#   st.image('public/bedrock.png', caption='Amazon Bedrock')
    st.button('Clear Screen', on_click=clear_screen)

# Store LLM generated responses
if "messages" not in st.session_state.keys():
    st.session_state.messages = [{"role": "assistant", "content": "TiDBのことについて学習しています。色々聞いてみてね！"}]

# Display or clear chat messages
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.write(message["content"])

# Chat Input - User Prompt
if prompt := st.chat_input():
    with st.chat_message("user"):
        st.markdown(prompt)
        st.session_state.messages.append({"role": "user", "content": prompt})

    with st.chat_message("assistant"):
        placeholder = st.empty()
        full_response = ''
        streaming_response = query_engine.query(prompt)
        for chunk in streaming_response.response_gen:
            full_response += chunk
            placeholder.markdown(full_response)
        placeholder.markdown(full_response)
        st.session_state.messages.append({"role": "assistant", "content": full_response})

