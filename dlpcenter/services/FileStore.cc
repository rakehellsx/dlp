#include "FileStore.h"
#include "Pg.h"
#include <filesystem>
#include <fstream>
#include <regex>
#include "utils/Platform.h"
namespace dlp {
namespace {
std::filesystem::path location(const std::string &relative) {
    if (!std::regex_match(relative, std::regex("[a-f0-9]{64}/(original|thumbnail\\.jpg)")))
        throw std::invalid_argument("无效的文件存储路径");
    return fileRoot() / relative;
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
    TemporaryFile temporary(path.parent_path());
    temporary.write(bytes);
    temporary.publish(path);
}
} // namespace dlp
