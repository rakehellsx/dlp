#include "FileStore.h"
#include "Pg.h"
#include <filesystem>
#include <fstream>
#include <regex>
#include <fcntl.h>
#include <unistd.h>
namespace dlp {
namespace {
std::filesystem::path location(const std::string &relative) {
    if (!std::regex_match(relative, std::regex("[a-f0-9]{64}/(original|thumbnail.jpg)")))
        throw std::invalid_argument("无效的文件存储路径");
    return std::filesystem::path(env("DLP_FILE_ROOT", "/var/lib/sentinel-dlp/files")) / relative;
}
} // namespace
std::string readStoredFile(const std::string &relative) {
    auto path = location(relative);
    if (std::filesystem::is_symlink(path) || std::filesystem::is_symlink(path.parent_path()))
        throw std::runtime_error("File symlink denied");
    std::ifstream in(path, std::ios::binary);
    if (!in)
        throw std::runtime_error("Stored file missing");
    return std::string(std::istreambuf_iterator<char>(in), {});
}
void storeFile(const std::string &relative, const std::string &bytes) {
    auto path = location(relative);
    std::filesystem::create_directories(path.parent_path());
    if (std::filesystem::exists(path)) {
        if (readStoredFile(relative) != bytes)
            throw std::runtime_error("Stored file integrity mismatch");
        return;
    }
    std::string pattern = path.string() + ".tmp-XXXXXX";
    std::vector<char> temp(pattern.begin(), pattern.end());
    temp.push_back(0);
    int fd = mkstemp(temp.data());
    if (fd < 0)
        throw std::runtime_error("Cannot create file");
    try {
        size_t pos = 0;
        while (pos < bytes.size()) {
            auto n = write(fd, bytes.data() + pos, bytes.size() - pos);
            if (n <= 0)
                throw std::runtime_error("Cannot write file");
            pos += n;
        }
        if (fsync(fd))
            throw std::runtime_error("Cannot sync file");
        close(fd);
        fd = -1;
        std::filesystem::rename(temp.data(), path);
    } catch (...) {
        if (fd >= 0)
            close(fd);
        unlink(temp.data());
        throw;
    }
}
} // namespace dlp
