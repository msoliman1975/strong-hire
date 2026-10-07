/**
 * The real voice connection: LiveKit in the browser. The candidate's microphone goes to the room,
 * and the interviewer's audio plays through a hidden <audio> element. Audio is never recorded.
 */
import { Room, RoomEvent, Track, type RemoteParticipant } from "livekit-client";

import { COACH_TOPIC, SESSION_TOPIC, encodeCommand, parseAgentMessage, type VoiceConnector } from "./voice";

export const connectLiveKit: VoiceConnector = async (join, handlers) => {
  const room = new Room({ adaptiveStream: true, dynacast: true });
  const audio: HTMLMediaElement[] = [];
  let leaving = false;
  const agentHere = (p: RemoteParticipant) => {
    if (p.isAgent) handlers.onAgentJoined();
  };

  room
    .on(RoomEvent.ParticipantConnected, agentHere)
    .on(RoomEvent.DataReceived, (payload, _participant, _kind, topic) => {
      if (topic !== SESSION_TOPIC) return;
      const message = parseAgentMessage(payload);
      if (message?.type === "state") handlers.onState(message.state);
      if (message?.type === "ended") handlers.onEnded();
    })
    .on(RoomEvent.TrackSubscribed, (track) => {
      if (track.kind !== Track.Kind.Audio) return;
      const element = track.attach();
      element.hidden = true;
      document.body.appendChild(element);
      audio.push(element);
    })
    .on(RoomEvent.TrackUnsubscribed, (track) => track.detach().forEach((e) => e.remove()))
    .on(RoomEvent.Reconnecting, () => handlers.onConnection("reconnecting"))
    .on(RoomEvent.Reconnected, () => handlers.onConnection("connected"))
    .on(RoomEvent.Disconnected, () => {
      audio.splice(0).forEach((e) => e.remove());
      if (!leaving) handlers.onConnection("disconnected");
    });

  await room.connect(join.livekit_url, join.token);
  await room.startAudio(); // the user clicked a button, so the browser lets the audio play
  await room.localParticipant.setMicrophoneEnabled(true, {
    echoCancellation: true,
    noiseSuppression: true,
  });
  room.remoteParticipants.forEach(agentHere);
  handlers.onConnection("connected");

  return {
    send: (command) =>
      room.localParticipant.publishData(encodeCommand(command), {
        reliable: true,
        topic: COACH_TOPIC,
      }),
    disconnect: async () => {
      leaving = true;
      await room.disconnect();
    },
  };
};
