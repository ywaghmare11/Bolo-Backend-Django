from django.urls import path

from apps.auth.views import LogoutView, RefreshView, RequestOtpView, VerifyOtpView

urlpatterns = [
    path("request-otp/", RequestOtpView.as_view(), name="auth-request-otp"),
    path("verify-otp/", VerifyOtpView.as_view(), name="auth-verify-otp"),
    path("refresh/", RefreshView.as_view(), name="auth-refresh"),
    path("logout/", LogoutView.as_view(), name="auth-logout"),
]
