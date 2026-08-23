class NormalizeApiTrailingSlashMiddleware:
    """
    docs/api/api-spec.md documents every endpoint without a trailing slash
    (POST /auth/request-otp, etc.) -- the exact contract bolo-web was built
    against (Express doesn't care about trailing slashes). This project's
    urls.py patterns use Django's own trailing-slash convention instead (needed
    for reverse()), so incoming request paths are normalized here before URL
    resolution rather than relying on CommonMiddleware's APPEND_SLASH, which
    can only redirect GET -- it 500s on POST/PATCH/DELETE since it can't
    replay the request body across a redirect.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path_info
        if path.startswith("/api/") and not path.endswith("/"):
            request.path_info = path + "/"
            request.META["PATH_INFO"] = request.path_info
        return self.get_response(request)
