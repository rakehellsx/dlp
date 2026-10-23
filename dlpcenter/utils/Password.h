#pragma once
#include <crypt.h>
#include <openssl/rand.h>
#include <openssl/crypto.h>
#include <stdexcept>
#include <string>
// Preserve the imported controller's BCrypt API using Ubuntu's libxcrypt bcrypt.
namespace BCrypt {
inline std::string generateHash(const std::string &password, unsigned long cost = 10) {
    char entropy[16], salt[CRYPT_GENSALT_OUTPUT_SIZE];
    if (RAND_bytes(reinterpret_cast<unsigned char *>(entropy), sizeof entropy) != 1 ||
        !crypt_gensalt_rn("$2b$", cost, entropy, sizeof entropy, salt, sizeof salt))
        throw std::runtime_error("Cannot generate bcrypt salt");
    crypt_data state{};
    const char *hash = crypt_r(password.c_str(), salt, &state);
    if (!hash || hash[0] == '*')
        throw std::runtime_error("bcrypt failed");
    return hash;
}
inline bool validatePassword(const std::string &password, const std::string &stored) {
    if (stored.rfind("$2", 0) != 0)
        return false;
    crypt_data state{};
    const char *actual = crypt_r(password.c_str(), stored.c_str(), &state);
    return actual && stored.size() == std::string(actual).size() &&
           CRYPTO_memcmp(actual, stored.data(), stored.size()) == 0;
}
} // namespace BCrypt
