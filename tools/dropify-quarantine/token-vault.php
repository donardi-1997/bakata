<?php
declare(strict_types=1);

namespace Bakata\Dropify;

use InvalidArgumentException;
use RuntimeException;

/** Offline primitive; not registered with WordPress or wired into Dropify. */
final class TokenVault
{
    public function __construct(private readonly string $keyId, #[\SensitiveParameter] private readonly string $key)
    {
        if (!extension_loaded('sodium')) {
            throw new RuntimeException('Token vault unavailable');
        }
        if (strlen($key) !== SODIUM_CRYPTO_AEAD_XCHACHA20POLY1305_IETF_KEYBYTES
            || preg_match('/\A[A-Za-z0-9_-]{1,32}\z/D', $keyId) !== 1) {
            throw new InvalidArgumentException('Invalid vault configuration');
        }
    }

    private function aad(string $store): string
    {
        if (preg_match('/\A[A-Za-z0-9:_-]{1,128}\z/D', $store) !== 1) {
            throw new InvalidArgumentException('Invalid store context');
        }
        return "bakata-dropify:v1\0" . $this->keyId . "\0" . $store;
    }

    public function seal(#[\SensitiveParameter] string $token, string $store): string
    {
        if ($token === '' || strlen($token) > 1000 || preg_match('/[\x00-\x20\x7f]/', $token)) {
            throw new InvalidArgumentException('Invalid token');
        }
        $nonce = random_bytes(SODIUM_CRYPTO_AEAD_XCHACHA20POLY1305_IETF_NPUBBYTES);
        $cipher = sodium_crypto_aead_xchacha20poly1305_ietf_encrypt($token, $this->aad($store), $nonce, $this->key);
        return 'v1.' . $this->keyId . '.' . sodium_bin2base64($nonce . $cipher, SODIUM_BASE64_VARIANT_URLSAFE_NO_PADDING);
    }

    public function open(#[\SensitiveParameter] string $envelope, string $store): string
    {
        $aad = $this->aad($store);
        $parts = explode('.', $envelope, 3);
        if (strlen($envelope) > 1500 || count($parts) !== 3 || $parts[0] !== 'v1' || $parts[1] !== $this->keyId) {
            throw new RuntimeException('Token envelope rejected');
        }
        try {
            $payload = sodium_base642bin($parts[2], SODIUM_BASE64_VARIANT_URLSAFE_NO_PADDING);
        } catch (\SodiumException) {
            throw new RuntimeException('Token envelope rejected');
        }
        $n = SODIUM_CRYPTO_AEAD_XCHACHA20POLY1305_IETF_NPUBBYTES;
        if (strlen($payload) <= $n + SODIUM_CRYPTO_AEAD_XCHACHA20POLY1305_IETF_ABYTES
            || strlen($payload) > $n + SODIUM_CRYPTO_AEAD_XCHACHA20POLY1305_IETF_ABYTES + 1000
            || sodium_bin2base64($payload, SODIUM_BASE64_VARIANT_URLSAFE_NO_PADDING) !== $parts[2]) {
            throw new RuntimeException('Token envelope rejected');
        }
        $plain = sodium_crypto_aead_xchacha20poly1305_ietf_decrypt(substr($payload, $n), $aad, substr($payload, 0, $n), $this->key);
        if ($plain === false) {
            throw new RuntimeException('Token envelope rejected');
        }
        return $plain;
    }

    public function __debugInfo(): array { return ['keyId' => $this->keyId]; }
    public function __serialize(): array { throw new RuntimeException('Vault serialization prohibited'); }
    public function __unserialize(array $data): void { throw new RuntimeException('Vault serialization prohibited'); }
}
