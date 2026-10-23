#include "Platform.h"
#include <openssl/rand.h>
#include <cstdlib>
#include <algorithm>
#include <stdexcept>
#include <system_error>
#include <vector>
#ifdef _WIN32
#include <windows.h>
#include <sddl.h>
#else
#include <fcntl.h>
#include <unistd.h>
#include <cerrno>
#endif

namespace dlp {
#ifdef _WIN32
std::wstring wide(const std::string &s) {
    if (s.empty())
        return {};
    auto n = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, s.data(),
                                 static_cast<int>(s.size()), nullptr, 0);
    if (!n)
        throw std::runtime_error("Invalid UTF-8 path");
    std::wstring result(n, 0);
    MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, s.data(), static_cast<int>(s.size()),
                        result.data(), n);
    return result;
}
#endif
std::string env(const char *name, const std::string &fallback) {
#ifdef _WIN32
    auto key = wide(name);
    auto n = GetEnvironmentVariableW(key.c_str(), nullptr, 0);
    if (!n)
        return fallback;
    std::wstring value(n, 0);
    auto copied = GetEnvironmentVariableW(key.c_str(), value.data(), n);
    if (copied >= n)
        throw std::runtime_error("Environment changed while reading");
    if (!copied)
        return fallback;
    auto bytes =
        WideCharToMultiByte(CP_UTF8, 0, value.data(), copied, nullptr, 0, nullptr, nullptr);
    std::string result(bytes, 0);
    WideCharToMultiByte(CP_UTF8, 0, value.data(), copied, result.data(), bytes, nullptr, nullptr);
    return result;
#else
    auto v = std::getenv(name);
    return v ? v : fallback;
#endif
}
std::tm utcTime(std::time_t value) {
    std::tm result{};
#ifdef _WIN32
    if (gmtime_s(&result, &value))
        throw std::runtime_error("Invalid timestamp");
#else
    if (!gmtime_r(&value, &result))
        throw std::runtime_error("Invalid timestamp");
#endif
    return result;
}
std::tm chinaTime(std::time_t value) {
    return utcTime(value + 8 * 3600);
}
std::time_t makeUtcTime(std::tm &value) {
#ifdef _WIN32
    auto result = _mkgmtime64(&value);
#else
    auto result = timegm(&value);
#endif
    if (result == -1)
        throw std::invalid_argument("Invalid date");
    value = utcTime(result);
    return result;
}
std::filesystem::path fileRoot() {
#ifdef _WIN32
    return std::filesystem::u8path(env("DLP_FILE_ROOT", "data/files"));
#else
    return std::filesystem::u8path(env("DLP_FILE_ROOT", "/var/lib/sentinel-dlp/files"));
#endif
}
TemporaryFile::TemporaryFile(const std::filesystem::path &directory) {
#ifdef _WIN32
    PSECURITY_DESCRIPTOR descriptor = nullptr;
    // Only the owning account and SYSTEM may access temporary evidence bytes.
    if (!ConvertStringSecurityDescriptorToSecurityDescriptorW(
            L"D:P(A;;GA;;;SY)(A;;GA;;;OW)", SDDL_REVISION_1, &descriptor, nullptr))
        throw std::runtime_error("Cannot create private file ACL");
    SECURITY_ATTRIBUTES security{sizeof(SECURITY_ATTRIBUTES), descriptor, FALSE};
    for (int attempt = 0; attempt < 10; ++attempt) {
        unsigned char random[16];
        if (RAND_bytes(random, sizeof random) != 1) {
            LocalFree(descriptor);
            throw std::runtime_error("Random generator failed");
        }
        std::string name = ".dlp-";
        for (auto b : random) {
            name += "0123456789abcdef"[b >> 4];
            name += "0123456789abcdef"[b & 15];
        }
        path_ = directory / name;
        auto h = CreateFileW(path_.c_str(), GENERIC_READ | GENERIC_WRITE, FILE_SHARE_READ,
                             &security, CREATE_NEW, FILE_ATTRIBUTE_NORMAL, nullptr);
        if (h != INVALID_HANDLE_VALUE) {
            CloseHandle(h);
            LocalFree(descriptor);
            return;
        }
        if (GetLastError() != ERROR_FILE_EXISTS)
            break;
    }
    LocalFree(descriptor);
    throw std::runtime_error("Cannot create private temporary file");
#else
    auto name = (directory / ".dlp-XXXXXX").string();
    std::vector<char> pattern(name.begin(), name.end());
    pattern.push_back(0);
    auto fd = mkstemp(pattern.data());
    if (fd < 0)
        throw std::runtime_error("Cannot create private temporary file");
    close(fd);
    path_ = pattern.data();
#endif
}
TemporaryFile::~TemporaryFile() {
    if (!path_.empty()) {
        std::error_code error;
        std::filesystem::remove(path_, error);
    }
}
void TemporaryFile::write(const std::string &bytes) {
#ifdef _WIN32
    auto h = CreateFileW(path_.c_str(), GENERIC_WRITE, 0, nullptr, TRUNCATE_EXISTING,
                         FILE_ATTRIBUTE_NORMAL, nullptr);
    if (h == INVALID_HANDLE_VALUE)
        throw std::runtime_error("Cannot open temporary file");
    size_t offset = 0;
    while (offset < bytes.size()) {
        DWORD written = 0;
        if (!WriteFile(h, bytes.data() + offset,
                       static_cast<DWORD>(std::min<size_t>(bytes.size() - offset, 1024 * 1024)),
                       &written, nullptr) ||
            !written) {
            CloseHandle(h);
            throw std::runtime_error("Cannot write temporary file");
        }
        offset += written;
    }
    auto ok = FlushFileBuffers(h);
    CloseHandle(h);
    if (!ok)
        throw std::runtime_error("Cannot flush temporary file");
#else
    auto fd = open(path_.c_str(), O_WRONLY | O_TRUNC | O_NOFOLLOW | O_CLOEXEC);
    if (fd < 0)
        throw std::runtime_error("Cannot open temporary file");
    size_t offset = 0;
    while (offset < bytes.size()) {
        auto n = ::write(fd, bytes.data() + offset, bytes.size() - offset);
        if (n < 0 && errno == EINTR)
            continue;
        if (n <= 0) {
            close(fd);
            throw std::runtime_error("Cannot write temporary file");
        }
        offset += n;
    }
    auto ok = fsync(fd);
    close(fd);
    if (ok)
        throw std::runtime_error("Cannot flush temporary file");
#endif
}
void TemporaryFile::publish(const std::filesystem::path &destination) {
#ifdef _WIN32
    if (!MoveFileExW(path_.c_str(), destination.c_str(),
                     MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH))
        throw std::runtime_error("Cannot publish stored file");
#else
    std::filesystem::rename(path_, destination);
#endif
    path_.clear();
}
} // namespace dlp
