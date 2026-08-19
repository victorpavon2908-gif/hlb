from django.urls import path

from . import payment_views, views

urlpatterns = [
    path("", views.home, name="hbl_home"),
    path("login/", views.login_view, name="hbl_login"),
    path("logout/", views.logout_view, name="hbl_logout"),
    path("registro/", views.register_view, name="hbl_register"),
    path("planes/", views.plans, name="hbl_plans"),
    path("billetera/", payment_views.wallet, name="hbl_wallet"),
    path("retiros/", views.withdrawals, name="hbl_withdrawals"),
    path("referidos/", views.referrals, name="hbl_referrals"),
    path("ruleta/", views.wheel, name="hbl_wheel"),
    path("api/ruleta/girar/", views.wheel_spin, name="hbl_wheel_spin"),
    path("regalos/", views.gifts, name="hbl_gifts"),
    path("perfil/", views.profile, name="hbl_profile"),
    path("api/perfil/zona-horaria/", views.update_timezone, name="hbl_update_timezone"),
    path("api/escucha/<int:assignment_id>/iniciar/", views.listen_start, name="hbl_listen_start"),
    path("api/escucha/<uuid:session_id>/ping/", views.listen_ping, name="hbl_listen_ping"),
    path("api/escucha/<uuid:session_id>/completar/", views.listen_complete, name="hbl_listen_complete"),

    # Binance Pay Merchant
    path("pagos/binance/retorno/", views.binance_return, name="hbl_binance_return"),
    path("pagos/binance/webhook/", views.binance_webhook, name="hbl_binance_webhook"),

    # PayPal Checkout Orders v2
    path("pagos/paypal/retorno/", payment_views.paypal_return, name="hbl_paypal_return"),
    path("pagos/paypal/cancelar/", payment_views.paypal_cancel, name="hbl_paypal_cancel"),
    path("pagos/paypal/webhook/", payment_views.paypal_webhook, name="hbl_paypal_webhook"),

    # Tilopay Hosted Payment Link
    path("pagos/tilopay/retorno/", payment_views.tilopay_return, name="hbl_tilopay_return"),
    path("pagos/tilopay/<uuid:deposit_id>/verificar/", payment_views.verify_tilopay, name="hbl_tilopay_verify"),

    # Verificación automática de depósitos USDT on-chain
    path("pagos/crypto/<uuid:deposit_id>/verificar/", payment_views.verify_crypto, name="hbl_crypto_verify"),

    path("terminos/", views.terms, name="hbl_terms"),
    path("offline/", views.offline, name="hbl_offline"),
    path("service-worker.js", views.service_worker, name="hbl_service_worker"),
    path("healthz/", views.healthz, name="hbl_healthz"),
]
