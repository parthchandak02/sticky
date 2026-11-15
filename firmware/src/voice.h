// Voice notes: record while the top key is held, upload, wait for the server's note.
#pragma once

#include <functional>
#include <string>

namespace voice {

// Records from the PDM mic while stillHeld() returns true (up to 60 s), then uploads as WAV.
// Returns the server's job id, or "" if nothing usable was recorded or the upload failed.
std::string recordAndUpload(const std::function<bool()>& stillHeld);
// Polls the job until the note is written (or failed). Returns true when done.
bool waitDone(const std::string& id, uint32_t timeoutMs = 90000);

}  // namespace voice
