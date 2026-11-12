# Publishing

`uvx --from git+https://github.com/xLinkOut/arrctl arrctl` works today without a PyPI release.

The short form `uvx arrctl` requires the package to exist on PyPI. The release
workflow already contains an optional PyPI job.

## Enable PyPI publishing

1. Create the project `arrctl` on <https://pypi.org> (or use a pending trusted
   publisher).
2. Create an API token scoped to that project.
3. Add it to the repository as the `PYPI_API_TOKEN` secret:

   ```bash
   gh secret set PYPI_API_TOKEN --repo xLinkOut/arrctl
   ```

4. Push a new version tag:

   ```bash
   git tag -a v0.1.7 -m "arrctl 0.1.2"
   git push origin v0.1.7
   ```

The `pypi` job runs `uv publish`. If the secret is missing it prints a message
and skips the upload, so releases still produce the GitHub release and the
container image.

After the first successful upload:

```bash
uvx arrctl --version
```

## Trusted publishing alternative

PyPI trusted publishing avoids storing a token. Configure the GitHub
environment/repository as a trusted publisher for the `release.yml` workflow,
then replace the token step with:

```yaml
permissions:
  id-token: write
- uses: pypa/gh-action-pypi-publish@release/v1
```

The current token-based job is intentionally simple and works with a normal
PyPI API token.
