from rest_framework.views import APIView

from apps.auth.serializers import RequestOtpSerializer, VerifyOtpSerializer
from apps.auth.services import AuthService
from apps.auth.tokens import REFRESH_COOKIE_NAME, clear_auth_cookies, set_auth_cookies
from apps.common.exceptions import AppError
from apps.common.permissions import AllowAny, IsAuthenticated
from apps.common.responses import success_response


class RequestOtpView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = RequestOtpSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"]

        AuthService.request_otp(email)
        return success_response(None, f"OTP sent to {email}")


class VerifyOtpView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = VerifyOtpSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        result = AuthService.verify_otp(
            serializer.validated_data["email"], serializer.validated_data["otp"],
        )
        user = result["user"]
        membership = result["membership"]

        response = success_response(
            {
                "userId": str(user.id),
                "name": user.name,
                "tenantId": str(membership.tenant_id),
                "tenantName": membership.tenant.name,
                "roleLevel": membership.role_level,
                "roleLabel": membership.role_label,
                "canBroadcast": membership.can_broadcast,
                "preferredLang": user.preferred_lang,
            },
            "Login successful",
        )
        set_auth_cookies(response, result["access_token"], result["refresh_token"])
        return response


class RefreshView(APIView):
    """AllowAny at the DRF layer -- the access token may already be expired
    when this is called, so it authenticates itself via the refresh_token
    cookie rather than requiring CookieJWTAuthentication to succeed."""

    permission_classes = [AllowAny]

    def post(self, request):
        raw_refresh = request.COOKIES.get(REFRESH_COOKIE_NAME)
        if not raw_refresh:
            raise AppError("No refresh token", 401, "UNAUTHENTICATED")

        result = AuthService.refresh(raw_refresh)
        response = success_response(None, "Token refreshed")
        set_auth_cookies(response, result["access_token"], result["refresh_token"])
        return response


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        raw_refresh = request.COOKIES.get(REFRESH_COOKIE_NAME)
        AuthService.logout(request.user, raw_refresh)

        response = success_response(None, "Logged out")
        clear_auth_cookies(response)
        return response
