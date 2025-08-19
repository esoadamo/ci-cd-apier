# ci-cd-APIer

APIer is a library that allows you to launch its backend code with Flask-like syntax using GitLab CI/CD.
All the requests and responses are processed with e2e encryption using [age](https://age-encryption.org/),
so nobody has access to the data except the sender (web page) and the receiver (GitLab job in memory).

## Usage example

**To see the full example, take a look at the [example repository](https://gitlab.com/esoadamo/ci-cd-apier-example/).**

Whenever the client calls a backend via APIer script, e.g.:

```js
const APIer = new APIer(
    '$AGE_PUBLIC_KEY$',
    '$GITLAB_PIPELINE_ENDPOINT$',
    '$GITLAB_TOKEN$'
);

const totalSum = await APIer.sendRequest('sumNumbers', [1, 2, 3, 4, 5]);
```

A pipeline is triggered. Example code that handles the request in the pipeline may be:

```python
app = APIER(environ["AGE_SECRET_KEY"])

@app.route("echo")
def endpoint_echo(data: any) -> str:
    return f"You said: {data}. Enjoy :)"
    
@app.route("sumNumbers")
def endpoint_sum(data: list[int]) -> str:
    return str(sum(data))

app.process_requests()
```

There also exists Python client for APIer in `ci_cd_apier.client` package.
