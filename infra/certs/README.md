# Extra CA certificates

Put extra root CA certificates here as `*.crt` files (PEM format) if your network
inspects TLS traffic (for example a corporate proxy). The Docker images trust every
`*.crt` file in this folder at build time.

`scripts/dev.ps1 up` copies the file named in `$env:SSL_CERT_FILE` here when this
folder has no `.crt` file yet. Files in this folder are not committed.
