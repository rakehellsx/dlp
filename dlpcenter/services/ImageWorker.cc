#include "ImageWorker.h"
#include "Pg.h"
#include <spawn.h>
#include <sys/wait.h>
#include <fcntl.h>
#include <unistd.h>
#include <fstream>
#include <filesystem>
#include <thread>
extern char **environ;
namespace dlp {
Json::Value imageWorker(const Json::Value &payload) {
    char input[] = "/tmp/dlp-input-XXXXXX", output[] = "/tmp/dlp-output-XXXXXX";
    int in = mkstemp(input), out = mkstemp(output);
    if (in < 0 || out < 0) {
        if (in >= 0) {
            close(in);
            unlink(input);
        }
        if (out >= 0) {
            close(out);
            unlink(output);
        }
        throw std::runtime_error("Cannot create image job");
    }
    struct Cleanup {
        int a, b;
        char *x, *y;
        ~Cleanup() {
            close(a);
            close(b);
            unlink(x);
            unlink(y);
        }
    } cleanup{in, out, input, output};
    auto data = dump(payload);
    size_t sent = 0;
    while (sent < data.size()) {
        auto n = write(in, data.data() + sent, data.size() - sent);
        if (n <= 0)
            throw std::runtime_error("Cannot write image job");
        sent += n;
    }
    lseek(in, 0, SEEK_SET);
    auto helper = env("DLP_IMAGE_HELPER", "dlpcenter/tools/image_processor.py");
    posix_spawn_file_actions_t actions;
    posix_spawn_file_actions_init(&actions);
    posix_spawn_file_actions_adddup2(&actions, in, STDIN_FILENO);
    posix_spawn_file_actions_adddup2(&actions, out, STDOUT_FILENO);
    posix_spawn_file_actions_addopen(&actions, STDERR_FILENO, "/dev/null", O_WRONLY, 0600);
    char *args[] = {const_cast<char *>("/usr/bin/python3"), helper.data(), nullptr};
    pid_t pid;
    auto error = posix_spawn(&pid, "/usr/bin/python3", &actions, nullptr, args, environ);
    posix_spawn_file_actions_destroy(&actions);
    if (error)
        throw std::runtime_error("Cannot start image processor");
    int status = 0;
    bool done = false;
    for (int i = 0; i < 350; i++) {
        if (waitpid(pid, &status, WNOHANG) == pid) {
            done = true;
            break;
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(100));
    }
    if (!done) {
        kill(pid, SIGKILL);
        waitpid(pid, &status, 0);
        throw std::invalid_argument("图片处理超时，请尝试更小的图片");
    }
    if (!WIFEXITED(status) || WEXITSTATUS(status) != 0 ||
        std::filesystem::file_size(output) > 24 * 1024 * 1024)
        throw std::runtime_error("Image processor failed");
    std::ifstream f(output);
    std::string response((std::istreambuf_iterator<char>(f)), {});
    auto result = parse(response);
    if (!result.get("ok", false).asBool())
        throw std::invalid_argument(result.get("error", "图片处理失败").asString());
    return result;
}
} // namespace dlp
