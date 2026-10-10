/**
 * The real voice connection: LiveKit in the browser. The candidate's microphone goes to the room,
 * and the interviewer's audio plays through a hidden <audio> element. Audio is never recorded.
 * The agent's audio track and its "lk.agent.state" attribute also go to the avatar.
 */
import { RemoteParticipant, Room, RoomEvent, Track } from "livekit-client";

import {
  AGENT_STATE_ATTRIBUTE,
  COACH_TOPIC,
  SESSION_TOPIC,
  encodeCommand,
  parseAgentActivity,
  parseAgentMessage,
  type VoiceConnector,
} from "./voice";

export const connectLiveKit: VoiceConnector = async (join, handlers) => {
  const room = new Room({ adaptiveStream: true, dynacast: true });
  const audio: HTMLMediaElement[] = [];
  let leaving = false;
  const agentHere = (p: RemoteParticipant) => {
    if (!p.isAgent) return;
    handlers.onAgentJoined();
    handlers.onActivity(parseAgentActivity(p.attributes[AGENT_STATE_ATTRIBUTE]));
  };

  room
    .on(RoomEvent.ParticipantConnected, agentHere)
    .on(RoomEvent.DataReceived, (payload, _participant, _kind, topic) => {
      if (topic !== SESSION_TOPIC) return;
      const message = parseAgentMessage(payload);
      if (message?.type === "state") handlers.onState(message.state);
      if (message?.type === "ended") handlers.onEnded();
    })
    .on(RoomEvent.ParticipantAttributesChanged, (_changed, participant) => {
      if (participant instanceof RemoteParticipant && participant.isAgent)
        handlers.onActivity(parseAgentActivity(participant.attributes[AGENT_STATE_ATTRIBUTE]));
    })
    .on(RoomEvent.TrackSubscribed, (track, _publication, participant) => {
      if (track.kind !== Track.Kind.Audio) return;
      const element = track.attach();
      element.hidden = true;
      document.body.appendChild(element);
      audio.push(element);
      if (participant.isAgent) handlers.onAgentAudio(track.mediaStreamTrack);
    })
    .on(RoomEvent.TrackUnsubscribed, (track, _publication, participant) => {
      track.detach().forEach((e) => e.remove());
      if (participant.isAgent && track.kind === Track.Kind.Audio) handlers.onAgentAudio(null);
    })
    .on(RoomEvent.Reconnecting, () => handlers.onConnection("reconnecting"))
    .on(RoomEvent.Reconnected, () => handlers.onConnection("connected"))
    .on(RoomEvent.Disconnected, () => {
      audio.splice(0).forEach((e) => e.remove());
      handlers.onAgentAudio(null);
      handlers.onActivity("idle");
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
