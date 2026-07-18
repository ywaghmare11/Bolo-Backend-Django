from rest_framework.response import Response


def success_response(data, message="", status=200):
    return Response({"success": True, "message": message, "data": data}, status=status)


def failure_response(message, status=400, code="ERROR", data=None):
    body = {"success": False, "error": {"code": code, "message": message}}
    if data is not None:
        # additive: some endpoints (e.g. verify-otp) document a top-level
        # `data` field alongside the error, e.g. {"attemptsRemaining": 2}
        body["data"] = data
    return Response(body, status=status)
