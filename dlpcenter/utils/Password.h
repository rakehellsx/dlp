#pragma once
#include "third_party/crypt_blowfish/crypt_blowfish.h"
#include <openssl/rand.h>
#include <openssl/crypto.h>
#include <stdexcept>
#include <string>
// The same reentrant bcrypt implementation on Windows and Linux; existing hashes stay valid.
namespace BCrypt {
inline std::string generateHash(const std::string &password, unsigned long cost = 10) {
    if (cost < 4 || cost > 16)
        throw std::invalid_argument("Invalid bcrypt cost");
    char entropy[16], salt[30], output[61];
    if (RAND_bytes(reinterpret_cast<unsigned char *>(entropy), sizeof entropy) != 1 ||
        !_crypt_gensalt_blowfish_rn("$2b$", cost, entropy, sizeof entropy, salt, sizeof salt))
        throw std::runtime_error("Cannot generate bcrypt salt");
    const char *hash = _crypt_blowfish_rn(password.c_str(), salt, output, sizeof output);
    if (!hash || hash[0] == '*')
        throw std::runtime_error("bcrypt failed");
    return hash;
}
inline bool validatePassword(const std::string &password, const std::string &stored) {
    if (stored.size() != 60 || (stored.substr(0, 4) != "$2a$" && stored.substr(0, 4) != "$2b$" &&
                                stored.substr(0, 4) != "$2y$"))
        return false;
    char output[61];
    const char *actual =
        _crypt_blowfish_rn(password.c_str(), stored.c_str(), output, sizeof output);
    return actual && stored.size() == std::string(actual).size() &&
           CRYPTO_memcmp(actual, stored.data(), stored.size()) == 0;
}
} // namespace BCrypt
