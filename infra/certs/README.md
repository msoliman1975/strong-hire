# Extra CA certificates

Put extra root CA certificates here as `*.crt` files (PEM format) if your network
inspects TLS traffic (for example a corporate proxy). Every service trusts every `*.crt` file
in this folder:

- The Python images (api, worker, voice, stt) add them at build time.
- Ollama reads them at run time through `SSL_CERT_DIR`.
- LiteLLM adds them to its CA bundle when the container starts (`SSL_CERT_FILE`).

`scripts/dev.ps1 up` copies the file named in `$env:SSL_CERT_FILE` here when this
folder has no `.crt` file yet. Files in this folder are not committed.
