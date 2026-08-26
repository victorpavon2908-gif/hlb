from django.urls import path

from . import payment_views, progressive_plans, views, withdrawal_views

urlpatterns = [
    path("", views.home, name="hbl_home"),
    path("login/", views.login_view, name="hbl_login"),
    path("logout/", views.logout_view, name="hbl_logout"),
    path("registro/", views.register_view, name="hbl_register"),
    path("planes/", progressive_plans.plans, name="hbl_plans"),
    path("billetera/", payment_views.wallet, name="hbl_wallet"),
    path("api/billetera/revalidar/", payment_views.recheck_crypto_deposits, name="hbl_crypto_recheck"),
    path("api/pagos/nowpayments/ipn/", payment_views.nowpayments_ipn, name="hbl_nowpayments_ipn"),
    path("retiros/", withdrawal_views.withdrawals, name="hbl_withdrawals"),
    path("referidos/", views.referrals, name="hbl_referrals"),
    path("ruleta/", views.wheel, name="hbl_wheel"),
    path("api/ruleta/girar/", views.wheel_spin, name="hbl_wheel_spin"),
    path("regalos/", views.gifts, name="hbl_gifts"),
    path("perfil/", views.profile, name="hbl_profile"),
    path("api/perfil/zona-horaria/", views.update_timezone, name="hbl_update_timezone"),
    path("api/escucha/<int:assignment_id>/iniciar/", views.listen_start, name="hbl_listen_start"),
    path("api/escucha/<uuid:session_id>/ping/", views.listen_ping, name="hbl_listen_ping"),
    path("api/escucha/<uuid:session_id>/completar/", views.listen_complete, name="hbl_listen_complete"),
    path("terminos/", views.terms, name="hbl_terms"),
    path("offline/", views.offline, name="hbl_offline"),
    path("service-worker.js", views.service_worker, name="hbl_service_worker"),
    path("healthz/", views.healthz, name="hbl_healthz"),
]
