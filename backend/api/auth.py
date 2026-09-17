import logging
import urllib.request
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from backend.core.config import SUPABASE_ANON_KEY, SUPABASE_JWT_SECRET, SUPABASE_URL

logger = logging.getLogger('ats_resume_scorer')

_bearer_scheme = HTTPBearer(auto_error=False)

_ASYMMETRIC_ALGS = ['ES256', 'RS256']

_jwks_client: jwt.PyJWKClient | None = None


def _get_jwks_client() -> jwt.PyJWKClient | None:
    """Build a PyJWKClient that sends the Supabase anon key as `apikey` header.
    Supabase's JWKS endpoint returns 401 without this header."""
    global _jwks_client
    if _jwks_client is not None:
        return _jwks_client
    if not SUPABASE_URL:
        return None

    jwks_url = f"{SUPABASE_URL.rstrip('/')}/auth/v1/.well-known/jwks.json"

    # PyJWKClient uses urllib internally; install an opener that injects the
    # required apikey / Authorization headers for every request it makes.
    if SUPABASE_ANON_KEY:
        opener = urllib.request.build_opener()
        opener.addheaders = [
            ('apikey', SUPABASE_ANON_KEY),
            ('Authorization', f'Bearer {SUPABASE_ANON_KEY}'),
        ]
        urllib.request.install_opener(opener)

    _jwks_client = jwt.PyJWKClient(jwks_url, cache_keys=True, lifespan=3600)
    return _jwks_client


def _decode_hs256(token: str) -> dict:
    """Attempt HS256 decode using SUPABASE_JWT_SECRET."""
    if not SUPABASE_JWT_SECRET:
        raise jwt.InvalidTokenError(
            'HS256 token received but SUPABASE_JWT_SECRET is not configured'
        )
    return jwt.decode(
        token,
        SUPABASE_JWT_SECRET,
        algorithms=['HS256'],
        audience='authenticated',
    )


def _verify_token(token: str) -> dict:
    header = jwt.get_unverified_header(token)
    alg = header.get('alg')

    if alg == 'HS256':
        return _decode_hs256(token)

    if alg in _ASYMMETRIC_ALGS:
        jwks_client = _get_jwks_client()
        if jwks_client is None:
            raise jwt.InvalidTokenError(
                'SUPABASE_URL not configured — cannot fetch JWKS to verify token'
            )
        try:
            signing_key = jwks_client.get_signing_key_from_jwt(token).key
            return jwt.decode(
                token,
                signing_key,
                algorithms=_ASYMMETRIC_ALGS,
                audience='authenticated',
            )
        except Exception as jwks_exc:
            # JWKS fetch failed — fall back to HS256 if a secret is available
            logger.warning(f'JWKS verification failed ({jwks_exc}); trying HS256 fallback')
            if SUPABASE_JWT_SECRET:
                return _decode_hs256(token)
            raise

    raise jwt.InvalidTokenError(f'Unsupported JWT algorithm: {alg}')


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> str:
    if creds is None or not creds.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail='Missing Authorization: Bearer <token> header',
            headers={'WWW-Authenticate': 'Bearer'},
        )

    if not SUPABASE_URL and not SUPABASE_JWT_SECRET:
        logger.error('Neither SUPABASE_URL (for JWKS) nor SUPABASE_JWT_SECRET configured')
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Auth not configured on the server',
        )

    try:
        payload = _verify_token(creds.credentials)
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail='Token expired — sign in again',
            headers={'WWW-Authenticate': 'Bearer'},
        )
    except jwt.InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f'Invalid token: {exc}',
            headers={'WWW-Authenticate': 'Bearer'},
        )
    except Exception as exc:
        logger.warning(f'JWT verification failed: {exc}')
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f'Token verification failed: {exc}',
            headers={'WWW-Authenticate': 'Bearer'},
        )

    user_id = payload.get('sub')
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail='Token missing subject claim',
        )
    return user_id
