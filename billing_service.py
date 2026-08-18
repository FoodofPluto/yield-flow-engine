"""Trusted Stripe billing orchestration for the FuruFlow sidecar."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Protocol
from urllib.parse import urlparse
from uuid import UUID

import stripe

from account_control import AccountOperationError, ServiceRoleAccountClient


ACTIVE_SUBSCRIPTION_STATUSES = frozenset({"active"})
SUPPORTED_SUBSCRIPTION_STATUSES = frozenset(
    {"inactive", "incomplete", "incomplete_expired", "trialing", "active", "past_due", "canceled", "unpaid", "paused"}
)


class BillingConfigurationError(RuntimeError):
    """Billing is unavailable because trusted configuration is unsafe or incomplete."""


class BillingOperationError(RuntimeError):
    """A safe user-facing billing operation could not be completed."""


class BillingWebhookInvalid(RuntimeError):
    """The submitted webhook could not be authenticated or parsed."""


@dataclass(frozen=True)
class BillingConfig:
    environment: str
    secret_key: str
    webhook_secret: str
    price_id: str
    product_id: str
    public_origin: str

    @classmethod
    def from_environment(cls) -> "BillingConfig":
        return cls.from_mapping(os.environ)

    @classmethod
    def from_mapping(cls, source: Mapping[str, str]) -> "BillingConfig":
        config = cls(
            environment=source.get("ENVIRONMENT", "").strip().lower(),
            secret_key=source.get("STRIPE_SECRET_KEY", "").strip(),
            webhook_secret=source.get("STRIPE_WEBHOOK_SECRET", "").strip(),
            price_id=source.get("STRIPE_PRICE_ID", "").strip(),
            product_id=source.get("STRIPE_PRODUCT_ID", "").strip(),
            public_origin=source.get("FURUFLOW_SESSION_BROKER_PUBLIC_ORIGIN", "").strip().rstrip("/"),
        )
        config.validate()
        return config

    def validate(self) -> None:
        if self.environment not in {"development", "test", "preview", "staging", "production"}:
            raise BillingConfigurationError("Billing environment is not configured.")
        credential_values = (self.secret_key, self.webhook_secret, self.price_id, self.product_id)
        if any(
            marker in value.lower()
            for value in credential_values
            for marker in ("replace", "placeholder", "example", "dummy", "your_")
        ):
            raise BillingConfigurationError("Stripe configuration contains a placeholder.")
        if not self.secret_key.startswith(("sk_test_", "sk_live_")) or len(self.secret_key) < 16:
            raise BillingConfigurationError("Stripe secret configuration is invalid.")
        if self.environment == "production" and not self.secret_key.startswith("sk_live_"):
            raise BillingConfigurationError("Production requires an explicit live-mode Stripe key.")
        if self.environment != "production" and self.secret_key.startswith("sk_live_"):
            raise BillingConfigurationError("Non-production billing cannot use a live-mode Stripe key.")
        if not self.webhook_secret.startswith("whsec_") or len(self.webhook_secret) < 16:
            raise BillingConfigurationError("Stripe webhook configuration is invalid.")
        if not self.price_id.startswith("price_") or len(self.price_id) < 10:
            raise BillingConfigurationError("Stripe price configuration is invalid.")
        if not self.product_id.startswith("prod_") or len(self.product_id) < 9:
            raise BillingConfigurationError("Stripe product configuration is invalid.")
        parsed = urlparse(self.public_origin)
        local_development = self.environment in {"development", "test"} and parsed.hostname in {"localhost", "127.0.0.1"}
        if (parsed.scheme != "https" and not local_development) or not parsed.netloc or parsed.path not in {"", "/"}:
            raise BillingConfigurationError("Billing public origin must be an HTTPS origin.")


class StripeGateway(Protocol):
    def create_customer(self, *, email: str, user_id: str, idempotency_key: str) -> Mapping[str, Any]: ...

    def create_checkout(self, **params: Any) -> Mapping[str, Any]: ...

    def create_portal(self, **params: Any) -> Mapping[str, Any]: ...

    def retrieve_subscription(self, subscription_id: str) -> Mapping[str, Any]: ...

    def construct_event(self, payload: bytes, signature: str, secret: str) -> Mapping[str, Any]: ...


class StripeSdkGateway:
    def __init__(self, secret_key: str):
        stripe.api_key = secret_key

    def create_customer(self, *, email: str, user_id: str, idempotency_key: str) -> Mapping[str, Any]:
        return stripe.Customer.create(
            email=email,
            metadata={"furuflow_user_id": user_id},
            idempotency_key=idempotency_key,
        )

    def create_checkout(self, **params: Any) -> Mapping[str, Any]:
        return stripe.checkout.Session.create(**params)

    def create_portal(self, **params: Any) -> Mapping[str, Any]:
        return stripe.billing_portal.Session.create(**params)

    def retrieve_subscription(self, subscription_id: str) -> Mapping[str, Any]:
        return stripe.Subscription.retrieve(subscription_id, expand=["items.data.price.product"])

    def construct_event(self, payload: bytes, signature: str, secret: str) -> Mapping[str, Any]:
        return stripe.Webhook.construct_event(payload, signature, secret)


def _uuid(value: Any) -> str | None:
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError):
        return None


def _string_id(value: Any, prefix: str) -> str | None:
    if not isinstance(value, str) or len(value) > 255:
        return None
    return value if re.fullmatch(rf"{re.escape(prefix)}[A-Za-z0-9_]+", value) else None


def _timestamp(value: Any) -> str | None:
    if not isinstance(value, (int, float)):
        return None
    try:
        return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()
    except (OSError, OverflowError, ValueError):
        return None


def _demo_active(entitlement: Mapping[str, Any]) -> bool:
    value = entitlement.get("demo_expires_at")
    if not isinstance(value, str):
        return False
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")) > datetime.now(timezone.utc)
    except ValueError:
        return False


class BillingService:
    def __init__(
        self,
        *,
        config: BillingConfig | None = None,
        accounts: ServiceRoleAccountClient | None = None,
        gateway: StripeGateway | None = None,
    ):
        self.config = config or BillingConfig.from_environment()
        self.accounts = accounts or ServiceRoleAccountClient()
        self.gateway = gateway or StripeSdkGateway(self.config.secret_key)

    def _eligible_identity(self, identity: Mapping[str, Any]) -> tuple[str, str]:
        user_id = _uuid(identity.get("id"))
        email = identity.get("email")
        verified = identity.get("email_confirmed_at") or identity.get("confirmed_at")
        if not user_id or not isinstance(email, str) or not email.strip() or not verified or identity.get("is_anonymous"):
            raise BillingOperationError("A verified account is required for billing.")
        try:
            entitlement = self.accounts.get_entitlement(user_id)
        except AccountOperationError as exc:
            raise BillingOperationError("Billing account state is temporarily unavailable.") from exc
        if _uuid(entitlement.get("user_id")) != user_id:
            raise BillingOperationError("Billing account state is temporarily unavailable.")
        if _demo_active(entitlement):
            raise BillingOperationError("Demo accounts cannot create billing state.")
        return user_id, email.strip().lower()

    def _owned_mapping(self, user_id: str, *, unavailable_message: str) -> Mapping[str, Any] | None:
        try:
            mapping = self.accounts.get_stripe_mapping(user_id)
        except AccountOperationError as exc:
            raise BillingOperationError(unavailable_message) from exc
        if mapping is None:
            return None
        if _uuid(mapping.get("user_id")) != user_id or mapping.get("provider") != "stripe":
            raise BillingOperationError(unavailable_message)
        customer = mapping.get("provider_customer_id")
        subscription = mapping.get("provider_subscription_id")
        if customer is not None and not _string_id(customer, "cus_"):
            raise BillingOperationError(unavailable_message)
        if subscription is not None and not _string_id(subscription, "sub_"):
            raise BillingOperationError(unavailable_message)
        return mapping

    def _customer_for(self, user_id: str, email: str) -> tuple[str, Mapping[str, Any] | None]:
        mapping = self._owned_mapping(user_id, unavailable_message="Billing setup is temporarily unavailable.")
        existing = _string_id((mapping or {}).get("provider_customer_id"), "cus_")
        if existing:
            return existing, mapping
        try:
            customer = self.gateway.create_customer(
                email=email,
                user_id=user_id,
                idempotency_key=f"furuflow-{self.config.environment}-customer-{user_id}",
            )
            customer_id = _string_id(customer.get("id"), "cus_")
            if not customer_id:
                raise BillingOperationError("Billing setup is temporarily unavailable.")
            self.accounts.set_stripe_customer(user_id=user_id, customer_id=customer_id)
            mapping = self._owned_mapping(user_id, unavailable_message="Billing setup is temporarily unavailable.")
            if not mapping or mapping.get("provider_customer_id") != customer_id:
                raise BillingOperationError("Billing setup is temporarily unavailable.")
            return customer_id, mapping
        except BillingOperationError:
            raise
        except AccountOperationError as exc:
            raise BillingOperationError("Billing setup is temporarily unavailable.") from exc
        except Exception as exc:
            raise BillingOperationError("Billing setup is temporarily unavailable.") from exc

    def create_checkout(self, identity: Mapping[str, Any]) -> str:
        user_id, email = self._eligible_identity(identity)
        customer_id, mapping = self._customer_for(user_id, email)
        if (mapping or {}).get("status") == "active":
            raise BillingOperationError("This account already has an active subscription.")
        try:
            session = self.gateway.create_checkout(
                mode="subscription",
                customer=customer_id,
                client_reference_id=user_id,
                metadata={"furuflow_user_id": user_id},
                subscription_data={"metadata": {"furuflow_user_id": user_id}},
                line_items=[{"price": self.config.price_id, "quantity": 1}],
                success_url=f"{self.config.public_origin}/?billing=return",
                cancel_url=f"{self.config.public_origin}/?billing=cancelled",
                allow_promotion_codes=False,
            )
        except Exception as exc:
            raise BillingOperationError("Checkout is temporarily unavailable.") from exc
        url = session.get("url")
        if not isinstance(url, str) or not url.startswith("https://checkout.stripe.com/"):
            raise BillingOperationError("Checkout is temporarily unavailable.")
        return url

    def create_portal(self, identity: Mapping[str, Any]) -> str:
        user_id, _email = self._eligible_identity(identity)
        mapping = self._owned_mapping(user_id, unavailable_message="Billing management is temporarily unavailable.")
        customer_id = _string_id((mapping or {}).get("provider_customer_id"), "cus_")
        subscription_id = _string_id((mapping or {}).get("provider_subscription_id"), "sub_")
        if not customer_id or not subscription_id:
            raise BillingOperationError("No managed subscription is available for this account.")
        try:
            session = self.gateway.create_portal(
                customer=customer_id,
                return_url=f"{self.config.public_origin}/?billing=return",
            )
        except Exception as exc:
            raise BillingOperationError("Billing management is temporarily unavailable.") from exc
        url = session.get("url")
        if not isinstance(url, str) or not url.startswith("https://billing.stripe.com/"):
            raise BillingOperationError("Billing management is temporarily unavailable.")
        return url

    def _is_pro_subscription(self, subscription: Mapping[str, Any]) -> bool:
        items = ((subscription.get("items") or {}).get("data") or [])
        for item in items:
            price = item.get("price") or {}
            product = price.get("product")
            product_id = product.get("id") if isinstance(product, Mapping) else product
            if price.get("id") == self.config.price_id and product_id == self.config.product_id:
                return True
        return False

    def _apply_subscription(
        self,
        subscription: Mapping[str, Any],
        *,
        event_id: str,
        event_created: int,
        checkout_session_id: str | None = None,
        target_user_id: str | None = None,
    ) -> None:
        if not self._is_pro_subscription(subscription):
            raise BillingOperationError("Webhook subscription does not match the configured Pro offer.")
        status = str(subscription.get("status") or "inactive")
        if status not in SUPPORTED_SUBSCRIPTION_STATUSES:
            status = "inactive"
        metadata_user = _uuid((subscription.get("metadata") or {}).get("furuflow_user_id"))
        if target_user_id and metadata_user and target_user_id != metadata_user:
            raise BillingOperationError("Webhook account mapping is inconsistent.")
        self.accounts.apply_stripe_subscription(
            user_id=target_user_id or metadata_user,
            customer_id=_string_id(subscription.get("customer"), "cus_"),
            subscription_id=_string_id(subscription.get("id"), "sub_"),
            status=status,
            event_created=event_created,
            event_id=event_id,
            checkout_session_id=checkout_session_id,
            period_end=_timestamp(subscription.get("current_period_end")),
            cancel_at_period_end=bool(subscription.get("cancel_at_period_end")),
        )

    @staticmethod
    def _invoice_subscription_id(invoice: Mapping[str, Any]) -> str | None:
        direct = _string_id(invoice.get("subscription"), "sub_")
        if direct:
            return direct
        details = (((invoice.get("parent") or {}).get("subscription_details")) or {})
        return _string_id(details.get("subscription"), "sub_")

    def _process_event(self, event_type: str, obj: Mapping[str, Any], *, event_id: str, event_created: int) -> None:
        if event_type == "checkout.session.completed":
            if obj.get("mode") != "subscription":
                return
            subscription_id = _string_id(obj.get("subscription"), "sub_")
            if not subscription_id:
                raise BillingOperationError("Checkout subscription is unavailable.")
            subscription = self.gateway.retrieve_subscription(subscription_id)
            checkout_user = _uuid(obj.get("client_reference_id")) or _uuid(
                (obj.get("metadata") or {}).get("furuflow_user_id")
            )
            self._apply_subscription(
                subscription,
                event_id=event_id,
                event_created=event_created,
                checkout_session_id=_string_id(obj.get("id"), "cs_"),
                target_user_id=checkout_user,
            )
        elif event_type in {
            "customer.subscription.created",
            "customer.subscription.updated",
            "customer.subscription.deleted",
        }:
            self._apply_subscription(obj, event_id=event_id, event_created=event_created)
        elif event_type in {"invoice.paid", "invoice.payment_succeeded", "invoice.payment_failed"}:
            subscription_id = self._invoice_subscription_id(obj)
            if subscription_id:
                self._apply_subscription(
                    self.gateway.retrieve_subscription(subscription_id),
                    event_id=event_id,
                    event_created=event_created,
                )

    def handle_webhook(self, payload: bytes, signature: str) -> bool:
        if not signature:
            raise BillingWebhookInvalid("Webhook signature is required.")
        try:
            event = self.gateway.construct_event(payload, signature, self.config.webhook_secret)
            event_id = event.get("id")
            event_type = event.get("type")
            event_created = event.get("created")
            obj = ((event.get("data") or {}).get("object"))
            if (
                not isinstance(event_id, str)
                or not isinstance(event_type, str)
                or not isinstance(event_created, int)
                or not isinstance(obj, Mapping)
            ):
                raise BillingWebhookInvalid("Webhook event is malformed.")
        except BillingWebhookInvalid:
            raise
        except Exception as exc:
            raise BillingWebhookInvalid("Webhook signature is invalid.") from exc

        try:
            if not self.accounts.begin_webhook_event(event_id, event_type):
                return False
            self._process_event(event_type, obj, event_id=event_id, event_created=event_created)
            self.accounts.finish_webhook_event(event_id, succeeded=True)
            return True
        except Exception as exc:
            try:
                self.accounts.finish_webhook_event(event_id, succeeded=False, error_code="fulfillment_failed")
            except AccountOperationError:
                pass
            if isinstance(exc, BillingOperationError):
                raise
            raise BillingOperationError("Webhook fulfillment failed.") from exc
