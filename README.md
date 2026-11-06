# Marketplace API

A multi-vendor marketplace backend built with Django and Django REST Framework.
Users register, open stores, list products, and buy from each other. Everything
they do is recorded in an activity log.

## Stack

| Package | Version |
|---|---|
| Python | 3.10 |
| Django | 3.2.12 |
| djangorestframework | 3.13.1 |
| drf-spectacular | 0.21.2 |
| django-filter | 21.1 |
| djangorestframework-simplejwt | 4.8.0 (+ PyJWT 2.3.0) |
| django-cors-headers | 3.11.0 |
| Pillow | 9.0.1 |
| pytz | 2021.3 |
| pytest / pytest-django / factory-boy | 6.2.5 / 4.5.2 / 3.2.1 |

## Quick start

```bash
python3.10 -m venv .venv
```

```bash
.venv/bin/pip install -r requirements-dev.txt
```

```bash
.venv/bin/python manage.py migrate
```

```bash
.venv/bin/python manage.py seed_demo
```

```bash
.venv/bin/python manage.py runserver
```

- Swagger UI: http://127.0.0.1:8000/api/docs/
- ReDoc: http://127.0.0.1:8000/api/redoc/
- OpenAPI document: http://127.0.0.1:8000/api/schema/
- Admin: http://127.0.0.1:8000/admin/ (seeded `admin` / `demo-pass-123`)

The `Makefile` wraps the same steps (`make install migrate seed run`, `make ci`).

## Domain

```
User ─┬─ Profile (1:1)
      ├─ Address (shipping / billing, one default per kind)
      ├─ Follow  (user → user)
      ├─ Store ── Product ─┬─ ProductImage (thumbnail generated on upload)
      │                    ├─ ProductVariant
      │                    ├─ Review          (one per author, soft-deletable)
      │                    └─ ProductQuestion (answered by the store owner)
      ├─ Cart ── CartItem
      ├─ Wishlist ── WishlistItem
      ├─ Coupon (store-scoped or platform-wide)
      ├─ Order ─┬─ OrderItem
      │         ├─ Payment
      │         └─ Shipment
      ├─ UserAction   (activity log, written automatically on every API write)
      ├─ Notification (follows, orders, new products from followed sellers)
      └─ SavedSearch
```

Apps live in `apps/`:

- `core`: base models, permissions, pagination, mixins, utilities, signals, middleware
- `accounts`: users, auth, profiles, addresses, follows
- `catalog`: categories, tags, stores, products, images, variants, reviews, questions
- `commerce`: carts, wishlists, coupons, orders, order items, payments, shipments, and the order service layer
- `activity`: user action log, notifications, saved searches

## API

All endpoints live under `/api/v1/`. Authentication uses JWT
(`Authorization: Bearer <access>`), with session auth as a fallback for the
browsable API and admin.

### Auth

| Method | Path | |
|---|---|---|
| POST | `/auth/register/` | Create an account |
| POST | `/auth/token/`, `/auth/token/refresh/`, `/auth/token/verify/` | JWT |
| POST | `/auth/logout/` | Blacklist a refresh token |
| GET/PUT/PATCH | `/auth/me/` | Current user |
| POST | `/auth/password/change/` | |
| POST | `/auth/email/verify/request/`, `/auth/email/verify/confirm/` | Signed-token email verification |

### CRUD resources (23)

Each resource supports `GET` list, `POST` create, `GET`/`PUT`/`PATCH`/`DELETE`
detail, plus filtering, search, ordering and pagination where it makes sense.

| Resource | Path | Extra actions |
|---|---|---|
| Users | `/users/` | `followers`, `following`, `follow`, `unfollow`, `reset-password` |
| Profiles | `/profiles/` | `mine` |
| Addresses | `/addresses/` | `set-default` |
| Follows | `/follows/` | |
| Categories | `/categories/` | `children` |
| Tags | `/tags/` | |
| Stores | `/stores/` | `set-status`, `close`, `stats` |
| Products | `/products/` | `publish`, `archive`, `adjust-stock`, `related`, `featured` |
| Product images | `/product-images/` | (multipart upload) |
| Product variants | `/product-variants/` | |
| Reviews | `/reviews/` | `helpful` |
| Questions | `/questions/` | `answer` |
| Carts | `/carts/` | `current`, `clear`, `checkout` |
| Cart items | `/cart-items/` | |
| Wishlists | `/wishlists/` | `move-to-cart` |
| Wishlist items | `/wishlist-items/` | |
| Coupons | `/coupons/` | `validate` |
| Orders | `/orders/` | `pay`, `cancel` |
| Order items | `/order-items/` | |
| Payments | `/payments/` | `refund` |
| Shipments | `/shipments/` | `set-status` |
| User actions | `/actions/` | `summary`, `export` (CSV) |
| Notifications | `/notifications/` | `mark-read`, `mark-all-read`, `unread-count` |
| Saved searches | `/saved-searches/` | `run` |

All DRF endpoints are documented through drf-spectacular. The schema currently
has 91 paths and 189 operations, and generates with **zero warnings**.

Business-rule failures (out of stock, invalid state transitions, bad coupons)
return `409 Conflict` with `{"detail": ..., "code": ...}`.

## Quality gates

CI runs the same checks on every push and pull request:

```bash
make ci
```

That runs:

1. `manage.py check --fail-level WARNING`
2. `manage.py makemigrations --check --dry-run`
3. `manage.py spectacular --validate --fail-on-warn`
4. `pytest` (134 tests), including:
   - `tests/test_schema.py`: the documented API surface must match
     `tests/snapshots/api_surface.txt` exactly. Every operation must be tagged
     and have a 2xx response, and the enum component names must stay stable.

## License

[MIT](LICENSE)
