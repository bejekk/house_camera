#!/usr/bin/env python3
import sys
from http.server import ThreadingHTTPServer
from config import HTTP_HOST, HTTP_PORT
from streamer import CameraStreamer
from detector import MotionDetector
from recorder import video_recorder
from storage import storage_manager
from web_server import StreamingHandler, init_web_context

def main():
    streamer = CameraStreamer(on_frame=video_recorder.feed_frame)

    def get_recorder_status():
        with video_recorder.lock:
            return {
                "is_recording": video_recorder.is_recording,
                "recording_enabled": video_recorder.recording_enabled,
                "ai_loaded": video_recorder.ai.available,
                "ai_last_detection": video_recorder.last_detection_summary,
                "ai_active_labels": list(video_recorder.detected_labels) if video_recorder.is_recording else []
            }

    detector = MotionDetector(
        streamer=streamer,
        on_motion=video_recorder.trigger_motion,
        get_recorder_status=get_recorder_status
    )
    video_recorder.motion_detector_getter = lambda: detector

    init_web_context(streamer, detector, video_recorder, storage_manager)

    streamer.start()
    detector.start()

    server_address = (HTTP_HOST, HTTP_PORT)
    httpd = ThreadingHTTPServer(server_address, StreamingHandler)
    print(f"CCTV Server running at http://{HTTP_HOST}:{HTTP_PORT}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        streamer.running = False
        detector.running = False
        video_recorder.stop_recording()
        if streamer.process:
            try:
                streamer.process.terminate()
            except Exception:
                pass

if __name__ == '__main__':
    main()
