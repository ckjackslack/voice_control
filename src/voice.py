import datetime
import json
import re
from dataclasses import (
    asdict,
    dataclass,
)
from enum import Enum, auto

import sounddevice
import speech_recognition as sr


_action_registry = {}


class MatchType(Enum):
    ALL_KEYWORDS = auto()
    DYNAMIC = auto()
    STARTS_WITH = auto()
    STATIC = auto()
    SUBSTRING = auto()


@dataclass
class CommandHistory:
    action: str
    timestamp: datetime.datetime
    args: dict

    def to_json(self):
        return json.dumps({
            "action": self.action,
            "timestamp": self.timestamp.isoformat(),
            "args": self.args,
        })


def register_action(pattern, match_type=MatchType.STATIC):
    def decorator(func):
        _action_registry[pattern] = (func, match_type)
        return func
    return decorator


class MatchAndPerformMixin:
    def perform_action(self, command):
        for pattern, (action, match_type) in self.action_registry.items():
            if self.is_match(command, pattern, match_type):
                return action(self)
        return "Command not recognized"

    @staticmethod
    def is_match(command, pattern, match_type):
        if match_type == MatchType.SUBSTRING and re.search(pattern, command):
            return True
        elif match_type == MatchType.ALL_KEYWORDS:
            return all(word in command for word in pattern.split())
        elif match_type == MatchType.STARTS_WITH and command.startswith(pattern):
            return True
        # Additional match types can be handled here
        return False


class VoiceCommandMixin(MatchAndPerformMixin):
    recognizer = sr.Recognizer()
    microphone = sr.Microphone()

    def __init__(self):
        self.action_registry = _action_registry
        self.history = []

    def recognize_speech_from_mic(self):
        with self.microphone as source:
            self.recognizer.adjust_for_ambient_noise(source)
            audio = self.recognizer.listen(source)

        try:
            return self.recognizer.recognize_google(audio)
        except sr.RequestError:
            return "API unavailable"
        except sr.UnknownValueError:
            return "Unable to recognize speech"
        except KeyboardInterrupt:
            pass

    def process_voice_command(self):
        print("Please speak a command...")
        command = self.recognize_speech_from_mic()
        print(f"You said: {command}")

        action_response = self.perform_action(command.lower())
        print(action_response)

    # def perform_action(self, command):
    #     for pattern, action in self.action_registry.items():
    #         if re.search(pattern, command):
    #             return action(self)
    #     return "Command not recognized"

    # def perform_action(self, command):
    #     for pattern, (action, match_type) in self.action_registry.items():
    #         if match_type == MatchType.DYNAMIC:
    #             match = re.match(pattern, command)
    #             if match:
    #                 action_response = action(self, **match.groupdict())
    #                 self.add_to_history(action.__name__, match.groupdict())
    #                 return action_response
    #         elif match_type == MatchType.STATIC and re.search(pattern, command):
    #                 return action(self)
    #     return "Command not recognized"

    def add_to_history(self, action, args):
        self.history.append(
            CommandHistory(action, datetime.datetime.now(), args)
        )

    def save_history(self, filename):
        with open(filename, "w") as file:
            json.dump([
                asdict(command)
                for command
                in self.history
            ],
            file,
            indent=4,
            default=str,
        )

    def load_and_replay_history(self, filename):
        with open(filename, "r") as file:
            commands = json.load(file)
            for command in commands:
                action = self.action_registry[command["action"]][0]
                action(self, **command["args"])


class TestControl(VoiceCommandMixin):
    @register_action('turn on the light', MatchType.SUBSTRING)
    def turn_on_light(self):
        return "Turning on the light"

    @register_action('play music', MatchType.STARTS_WITH)
    def play_music(self):
        return "Playing music"


class PaintAppControl(VoiceCommandMixin):
    @register_action(r'make rectangle of width (?P<width>\d+) and height (?P<height>\d+) with top left corner at (?P<position>.+)', MatchType.DYNAMIC)
    def make_rectangle(self, width, height, position):
        return f"Making rectangle of width {width}, height {height} at {position}"


def main():
    paint_app = PaintAppControl()
    # paint_app.process_voice_command()
    # paint_app.save_history('command_history.json')
    # paint_app.load_and_replay_history('command_history.json')


if __name__ == "__main__":
    main()
