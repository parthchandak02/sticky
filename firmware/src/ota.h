// Over-the-air updates from sticky-server, with a trial boot and automatic rollback.
//
// A freshly installed build boots "on trial". It calls ota::markGood() once it has drawn a frame
// from the server. If it boots three times without doing so, ota::bootCheck() switches back to the
// previous slot. A version that failed is remembered and never offered again.
#pragma once

#include <string>

namespace ota {

const char* boardTag();  // "CROSSPOINT-BOARD-V1:sticky;", embedded in every image

// Call first thing in setup(). May reboot into the previous build.
void bootCheck();
// The running build proved itself (drew a server frame).
void markGood();
bool onTrial();
// Check the manifest; when a newer, untried build exists, download, verify and reboot into it.
// Returns a short status for logs and the console.
std::string checkAndInstall(const std::string& manifestPath);

}  // namespace ota
