#pragma once
#include <ctime>
#include <filesystem>
#include <string>

namespace dlp {
std::string env(const char *name, const std::string &fallback = "");
std::tm utcTime(std::time_t value);
std::tm chinaTime(std::time_t value);
std::time_t makeUtcTime(std::tm &value);
std::filesystem::path fileRoot();
// Secure, exclusively created file, automatically removed unless published.
class TemporaryFile {
    std::filesystem::path path_;

  public:
    explicit TemporaryFile(
        const std::filesystem::path &directory = std::filesystem::temp_directory_path());
    ~TemporaryFile();
    TemporaryFile(const TemporaryFile &) = delete;
    TemporaryFile &operator=(const TemporaryFile &) = delete;
    const std::filesystem::path &path() const {
        return path_;
    }
    void write(const std::string &bytes);
    void publish(const std::filesystem::path &destination);
};
#ifdef _WIN32
std::wstring wide(const std::string &utf8);
#endif
} // namespace dlp
