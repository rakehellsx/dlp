# crypt_blowfish

Openwall crypt_blowfish by Solar Designer, vendored from
https://github.com/trusch/libbcrypt/tree/d6523c370de6e724ce4ec703e2449b5b028ea3b1
(`src/crypt_blowfish.c` and `include/bcrypt/crypt_blowfish.h`).
The source/header contain the original public-domain / permissive license notice.
The wrapper repository MIT license is retained in LICENSE.

Local changes: normalize the header include path and force the portable C path
(no external x86 assembly), and add C++ extern "C" guards to the header. No changes to the bcrypt algorithm or runtime self-test.
OpenSSL RAND_bytes supplies entropy in utils/Password.h. All platforms generate
$2b$ bcrypt hashes and accept existing $2a$ / $2b$ / $2y$ hashes.
