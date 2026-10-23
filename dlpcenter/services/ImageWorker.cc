#include "ImageWorker.h"
#include "Pg.h"
#include "utils/Platform.h"
#include <fstream>
#include <filesystem>
#include <thread>
#include <chrono>
#ifdef _WIN32
#include <windows.h>
#else
#include <spawn.h>
#include <sys/wait.h>
#include <fcntl.h>
#include <unistd.h>
#include <cerrno>
extern char **environ;
#endif
namespace dlp {
namespace {
#ifdef _WIN32
struct Handle {
    HANDLE value = INVALID_HANDLE_VALUE;
    explicit Handle(HANDLE v) : value(v) {}
    ~Handle() {
        if (value && value != INVALID_HANDLE_VALUE)
            CloseHandle(value);
    }
    Handle(const Handle &) = delete;
};
// Windows command-line escaping, without invoking cmd.exe or PowerShell.
std::wstring quote(const std::wstring &arg) {
    std::wstring result = L"\"";
    size_t slashes = 0;
    for (auto c : arg) {
        if (c == L'\\') {
            ++slashes;
            continue;
        }
        result.append(slashes * (c == L'"' ? 2 : 1), L'\\');
        slashes = 0;
        if (c == L'"')
            result += L'\\';
        result += c;
    }
    result.append(slashes * 2, L'\\');
    return result + L'"';
}
void processImage(const std::filesystem::path &input, const std::filesystem::path &output) {
    SECURITY_ATTRIBUTES inherit{sizeof(SECURITY_ATTRIBUTES), nullptr, TRUE};
    Handle in(CreateFileW(input.c_str(), GENERIC_READ, FILE_SHARE_READ, &inherit, OPEN_EXISTING,
                          FILE_ATTRIBUTE_NORMAL, nullptr));
    Handle out(CreateFileW(output.c_str(), GENERIC_WRITE, FILE_SHARE_READ, &inherit,
                           TRUNCATE_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr));
    Handle err(CreateFileW(L"NUL", GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE, &inherit,
                           OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr));
    if (in.value == INVALID_HANDLE_VALUE || out.value == INVALID_HANDLE_VALUE ||
        err.value == INVALID_HANDLE_VALUE)
        throw std::runtime_error("Cannot open image job files");
    STARTUPINFOEXW startup{};
    startup.StartupInfo.cb = sizeof startup;
    startup.StartupInfo.dwFlags = STARTF_USESTDHANDLES;
    startup.StartupInfo.hStdInput = in.value;
    startup.StartupInfo.hStdOutput = out.value;
    startup.StartupInfo.hStdError = err.value;
    SIZE_T size = 0;
    InitializeProcThreadAttributeList(nullptr, 1, 0, &size);
    std::vector<unsigned char> buffer(size);
    startup.lpAttributeList = reinterpret_cast<LPPROC_THREAD_ATTRIBUTE_LIST>(buffer.data());
    if (!InitializeProcThreadAttributeList(startup.lpAttributeList, 1, 0, &size))
        throw std::runtime_error("Cannot initialize image process attributes");
    struct Attributes {
        LPPROC_THREAD_ATTRIBUTE_LIST value;
        ~Attributes() {
            DeleteProcThreadAttributeList(value);
        }
    } attributes{startup.lpAttributeList};
    HANDLE handles[] = {in.value, out.value, err.value};
    if (!UpdateProcThreadAttribute(startup.lpAttributeList, 0, PROC_THREAD_ATTRIBUTE_HANDLE_LIST,
                                   handles, sizeof handles, nullptr, nullptr))
        throw std::runtime_error("Cannot restrict image process handles");
    // Closing the job kills both Python and any Tesseract descendant on timeout or error.
    Handle job(CreateJobObjectW(nullptr, nullptr));
    JOBOBJECT_EXTENDED_LIMIT_INFORMATION limits{};
    limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
    if (!job.value || !SetInformationJobObject(job.value, JobObjectExtendedLimitInformation,
                                               &limits, sizeof limits))
        throw std::runtime_error("Cannot initialize image process job");
    auto command = quote(wide(env("DLP_PYTHON", "python.exe"))) + L" -X utf8 " +
                   quote(wide(env("DLP_IMAGE_HELPER", "dlpcenter/tools/image_processor.py")));
    PROCESS_INFORMATION process{};
    if (!CreateProcessW(nullptr, command.data(), nullptr, nullptr, TRUE,
                        CREATE_SUSPENDED | CREATE_NO_WINDOW | EXTENDED_STARTUPINFO_PRESENT, nullptr,
                        nullptr, &startup.StartupInfo, &process))
        throw std::runtime_error("Cannot start DLP_PYTHON image processor");
    Handle child(process.hProcess), thread(process.hThread);
    if (!AssignProcessToJobObject(job.value, child.value)) {
        TerminateProcess(child.value, 1);
        WaitForSingleObject(child.value, INFINITE);
        throw std::runtime_error("Cannot assign image process job");
    }
    if (ResumeThread(thread.value) == static_cast<DWORD>(-1))
        throw std::runtime_error("Cannot resume image processor");
    auto wait = WaitForSingleObject(child.value, 35000);
    if (wait != WAIT_OBJECT_0) {
        TerminateJobObject(job.value, 1);
        WaitForSingleObject(child.value, INFINITE);
        throw std::invalid_argument("图片处理超时，请尝试更小的图片");
    }
    DWORD status = 1;
    if (!GetExitCodeProcess(child.value, &status) || status)
        throw std::runtime_error("Image processor failed");
}
#else
void processImage(const std::filesystem::path &input, const std::filesystem::path &output) {
    struct Files {
        int in, out;
        ~Files() {
            if (in >= 0)
                close(in);
            if (out >= 0)
                close(out);
        }
    } files{open(input.c_str(), O_RDONLY | O_CLOEXEC | O_NOFOLLOW),
            open(output.c_str(), O_WRONLY | O_TRUNC | O_CLOEXEC | O_NOFOLLOW)};
    if (files.in < 0 || files.out < 0)
        throw std::runtime_error("Cannot open image job files");
    auto python = env("DLP_PYTHON", "/usr/bin/python3"),
         helper = env("DLP_IMAGE_HELPER", "dlpcenter/tools/image_processor.py");
    posix_spawn_file_actions_t actions;
    auto error = posix_spawn_file_actions_init(&actions);
    if (error)
        throw std::runtime_error("Cannot initialize image processor");
    if (!(error = posix_spawn_file_actions_adddup2(&actions, files.in, STDIN_FILENO)))
        error = posix_spawn_file_actions_adddup2(&actions, files.out, STDOUT_FILENO);
    if (!error)
        error =
            posix_spawn_file_actions_addopen(&actions, STDERR_FILENO, "/dev/null", O_WRONLY, 0600);
    char utf8[] = "utf8", option[] = "-X";
    char *args[] = {python.data(), option, utf8, helper.data(), nullptr};
    pid_t pid = -1;
    if (!error)
        error = posix_spawnp(&pid, python.c_str(), &actions, nullptr, args, environ);
    posix_spawn_file_actions_destroy(&actions);
    if (error)
        throw std::runtime_error("Cannot start DLP_PYTHON image processor");
    int status = 0;
    bool done = false;
    for (int i = 0; i < 350; i++) {
        auto result = waitpid(pid, &status, WNOHANG);
        if (result == pid) {
            done = true;
            break;
        }
        if (result == -1 && errno != EINTR)
            break;
        std::this_thread::sleep_for(std::chrono::milliseconds(100));
    }
    if (!done) {
        kill(pid, SIGKILL);
        while (waitpid(pid, &status, 0) < 0 && errno == EINTR) {
        }
        throw std::invalid_argument("图片处理超时，请尝试更小的图片");
    }
    if (!WIFEXITED(status) || WEXITSTATUS(status))
        throw std::runtime_error("Image processor failed");
}
#endif
} // namespace
Json::Value imageWorker(const Json::Value &payload) {
    TemporaryFile input, output;
    input.write(dump(payload));
    processImage(input.path(), output.path());
    if (std::filesystem::file_size(output.path()) > 24 * 1024 * 1024)
        throw std::runtime_error("Image processor output too large");
    std::ifstream f(output.path(), std::ios::binary);
    std::string response((std::istreambuf_iterator<char>(f)), {});
    auto result = parse(response);
    if (!result.get("ok", false).asBool())
        throw std::invalid_argument(result.get("error", "图片处理失败").asString());
    return result;
}
} // namespace dlp
