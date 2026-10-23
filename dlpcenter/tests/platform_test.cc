#include "utils/Platform.h"
#include "utils/Password.h"
#include "services/Pg.h"
#include "services/Validation.h"
#include "services/FileStore.h"
#include "services/ImageWorker.h"
#include <filesystem>
#include <iostream>
#include <fstream>
#include <functional>
#ifdef _WIN32
#include <windows.h>
#endif
namespace fs = std::filesystem;
void check(bool ok, const char *message) {
    if (!ok)
        throw std::runtime_error(message);
}
void rejects(const std::function<void()> &f) {
    try {
        f();
    } catch (const std::exception &) {
        return;
    }
    throw std::runtime_error("Expected rejection");
}
void environment(const char *key, const std::string &value) {
#ifdef _WIN32
    check(SetEnvironmentVariableW(dlp::wide(key).c_str(), dlp::wide(value).c_str()) != 0,
          "SetEnvironmentVariableW");
#else
    check(setenv(key, value.c_str(), 1) == 0, "setenv");
#endif
}
int main() {
    fs::path directory;
    try {
        // Hash made with Python bcrypt, representing an existing database password.
        const std::string sha = "8872437f237d9fa876c2d927b18b8b90d0286aaac6bf7ead900d5a72d8ccc59b";
        const std::string stored = "$2b$04$OmrMDDFzutiMD.6/nLNlIu30Bw.82ACxv2Y1YSxxLiHIPF3E7Tes6";
        for (auto prefix : {"$2a$", "$2b$", "$2y$"})
            check(BCrypt::validatePassword(sha, std::string(prefix) + stored.substr(4)),
                  "Existing Python bcrypt hash");
        check(!BCrypt::validatePassword("wrong", stored) && !BCrypt::validatePassword(sha, "bad"),
              "Password rejection");
        auto generated = BCrypt::generateHash(sha, 4), second = BCrypt::generateHash(sha, 4);
        check(generated != second && BCrypt::validatePassword(sha, generated),
              "Random salted bcrypt round-trip");
        check(dlp::chinaTime(0).tm_hour == 8 && dlp::utcTime(0).tm_hour == 0,
              "Host independent Asia/Shanghai timestamps");
        Json::Value metadata;
        metadata["title"] = "跨平台核验";
        metadata["ip"] = "2001:0db8::1";
        metadata["time"] = "2026-10-23T02:30:00Z";
        auto validated = dlp::metadata(metadata);
        check(validated["ip"] == "2001:db8::1" && validated["time"] == "2026-10-23 10:30:00",
              "IPv6 and UTC conversion");
        metadata["time"] = "2026-02-30 10:30:00";
        rejects([&] { dlp::metadata(metadata); });
        directory = fs::temp_directory_path() / fs::u8path("dlp 测试-" + dlp::randomId(""));
        fs::create_directory(directory);
        environment("DLP_FILE_ROOT", directory.u8string());
        auto relative = std::string(64, 'a') + "/original";
        std::string bytes("\x00\x01\xff\r\n", 5);
        dlp::storeFile(relative, bytes);
        dlp::storeFile(relative, bytes);
        check(dlp::readStoredFile(relative) == bytes, "Binary disk evidence and UTF-8 path");
        rejects([&] { dlp::storeFile(relative, "changed"); });
        rejects([&] { dlp::readStoredFile("../secret"); });
        rejects([&] { dlp::readStoredFile(std::string(64, 'a') + "/thumbnailXjpg"); });
        fs::path removed;
        {
            dlp::TemporaryFile file(directory);
            removed = file.path();
            file.write(bytes);
            check(fs::file_size(removed) == 5, "Temporary file write");
        }
        check(!fs::exists(removed), "Temporary file cleanup");
        // Exercise CreateProcessW / posix_spawnp with spaces and Chinese characters in the helper
        // path.
        auto helper = directory / fs::u8path("图片 helper.py");
        fs::copy_file(
            fs::u8path(dlp::env("DLP_IMAGE_HELPER", "dlpcenter/tools/image_processor.py")), helper);
        environment("DLP_IMAGE_HELPER", helper.u8string());
        Json::Value request;
        request["action"] = "capabilities";
        check(dlp::imageWorker(request)["images"].asBool(), "Image subprocess in a Unicode path");
        request["action"] = "invalid";
        rejects([&] { dlp::imageWorker(request); });
        fs::remove_all(directory);
        std::cout << "PASS portable bcrypt, dates, IPv6, atomic disk files, UTF-8 subprocess and "
                     "cleanup\n";
        return 0;
    } catch (const std::exception &e) {
        if (!directory.empty()) {
            std::error_code error;
            fs::remove_all(directory, error);
        }
        std::cerr << e.what() << '\n';
        return 1;
    }
}
