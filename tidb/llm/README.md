# Vector Store on TiDB Cloud Serverless (RAG) and Amazon Bedrock


### Pre-Preparation

- TiDB Cloud Serverless (Free Tier)
```
5.7.28-TiDB-Serverless [(none)]> select @@version;
+-------------------------------+
| @@version                     |
+-------------------------------+
| 8.0.11-TiDB-v7.5.2-serverless |
+-------------------------------+
```
- Amazon Bedrock
```
llm = BedrockConverse(model="anthropic.claude-3-sonnet-20240229-v1:0")
embed_model = BedrockEmbedding(model="amazon.titan-embed-text-v2:0")
```
- Python and PiP
```
$ python3 -V
Python 3.11.12

$ pip3 --version
pip 25.0.1 from /home/ec2-user/.local/lib/python3.11/site-packages/pip (python 3.11)

```

- Using venv for testing purpose

```
python -m venv .venv
source .venv/bin/activate
```
- Install Required Packages 

```
pip install -r requirements.txt
```

- TiDB Access Parameters

```
export TIDB_HOST=<Host>.tidbcloud.com
export TIDB_PORT=4000
export TIDB_USER=<TiDB User>
export TIDB_PASSWORD=<TiDB Password>
export TIDB_DB_NAME=<TiDB Schema>
```

- Token for Accessing AWS Bedrock

```
export AWS_DEFAULT_REGION=<Region>
export AWS_ACCESS_KEY_ID=<ID>
export AWS_SECRET_ACCESS_KEY=<Access Key>
export AWS_SESSION_TOKEN=<Session Token>
```
* If "~/.aws/credentials" is already configured, it is ok.

### Import Text Data to the Table (RAG )

```
python prepare.py
```

### Run Streamlit for Providing Browser Interface for RAG

```
streamlit run main.py
```

### Output

- RAG on TiDB Cloud Serverless
<img src="https://github.com/rdbms-at-twitter/distribution_databases/blob/main/tidb/llm/img/TiDB-Cloud-Serverless.png" alt="TiDB Cloud" title="TiDB Cloud">

- Streamlit and asking for question to Bedrock.
<img src="https://github.com/rdbms-at-twitter/distribution_databases/blob/main/tidb/llm/img/RAG.png" alt="streamlit" title="streamlit">


### Rederence 

https://zenn.dev/koiping/articles/a4362c8b1c0ee8

Thanks
