""" python events parsing libary """
import json
from typing import Tuple, Optional
import struct
import re

_base_types = {
    "uint8_t": {"size": 1, "unpack": struct.Struct('<B').unpack},
    "int8_t": {"size": 1, "unpack": struct.Struct('<b').unpack},
    "uint16_t": {"size": 2, "unpack": struct.Struct('<H').unpack},
    "int16_t": {"size": 2, "unpack": struct.Struct('<h').unpack},
    "uint32_t": {"size": 4, "unpack": struct.Struct('<I').unpack},
    "int32_t": {"size": 4, "unpack": struct.Struct('<i').unpack},
    "uint64_t": {"size": 8, "unpack": struct.Struct('<Q').unpack},
    "int64_t": {"size": 8, "unpack": struct.Struct('<q').unpack},
    "float": {"size": 4, "unpack": struct.Struct('<f').unpack},
}


class ParserException(Exception):
    """
    Exception to indicate a parser error.
    """


class ParsedEvent:
    """ representation of a parsed event (with metadata) """

    def __init__(self, event: dict, event_extras: dict, arguments: bytes,
                 events: dict, profile: str, debug: bool):
        self._event = event
        self._event_extras = event_extras
        self._arguments = arguments
        self._events = events
        self._profile = profile
        self._debug = debug

        self._values = []  # tuples of (value, enum)
        offset = 0
        for arg in self._event.get('arguments', []):
            base_type, enum = self._get_basetype(arg)
            size = _base_types[base_type]["size"]
            value, = _base_types[base_type]["unpack"](self._arguments[offset:offset + size])
            self._values.append((value, enum))
            offset += size

        self._debug_print("Event: {}, {}, values={}".format(self.event_id(),
                                                            self.name(), self._values))

    def _get_basetype(self, event_arg: dict) -> Tuple[str, Optional[dict]]:
        """ get the basic type, and the enum definition if it's an enum """
        arg_type = event_arg['type']
        if arg_type in _base_types:
            return arg_type, None
        # enum
        if '::' in arg_type:
            enum_type = arg_type
        else:
            enum_type = self.namespace() + '::' + arg_type
        enum = self._event_extras['enums'][enum_type]
        return (enum['type'], enum)

    def _debug_print(self, msg: str):
        """ debug output """
        if self._debug:
            print(msg)

    def event_id(self) -> int:
        """ get event ID """
        return self._event_extras['id']

    def name(self) -> str:
        """ get event name """
        return self._event['name']

    def namespace(self) -> str:
        """ get event namespace """
        return self._event_extras['namespace']

    def message(self) -> str:
        """ get event message """
        return self._process_message(self._event['message'])

    def description(self) -> str:
        """ get event description """
        if 'description' not in self._event:
            return ''
        return self._process_message(self._event['description'])

    def type(self) -> str:
        """ get event type """
        return self._event.get('type', '')

    def group(self) -> str:
        """ get event group name """
        return self._event_extras['group']

    def num_arguments(self) -> int:
        """ get number of arguments """
        if 'arguments' in self._event:
            return len(self._event['arguments'])
        return 0

    def argument_value(self, idx: int):
        """ get argument value (not enum type) """
        return self._values[idx][0]

    def argument_enum(self, idx: int):
        """ get argument enum type or None """
        return self._values[idx][1]

    def argument_display_value(self, idx: int):
        """ get argument to display (for enum's it's the enum entry/bits) """
        value, enum = self._values[idx]
        if enum is None:
            return value

        if enum.get('is_bitfield', False):
            size = _base_types[enum['type']]['size']
            ret_value = ""
            had_bit = False
            separator = enum.get('separator', '|')
            for i in range(size * 8):
                bit = 1 << i
                if value & bit:
                    if had_bit:
                        ret_value += separator
                    found = False
                    for entry_value in enum['entries']:
                        entry = enum['entries'][entry_value]
                        if int(entry_value) == bit:
                            ret_value += entry['description']
                            found = True
                            break
                    if not found:
                        ret_value += '(unknown: {})'.format(value)
                    had_bit = True
            return ret_value

        for entry_value in enum['entries']:
            entry = enum['entries'][entry_value]
            # could turn this into a map to make this more efficient...
            if int(entry_value) == value:
                return entry['description']
        return '(unknown: {})'.format(value)

    def _process_message(self, msg: str) -> str:
        """
         * Supported parsing:
         * - characters can be escaped with \\, e.g. '\\<', '\\{'
         * - tags:
         *   - <profile name="[!]NAME">CONTENT</profile>
         *   - <a [href="URL"]>CONTENT</a>
         *     if href is not found, use CONTENT as url
         *   - <param>PARAM_NAME</param>
         *   - unknown tags are ignored (including content)
         *   - no nested tags of the same type
         * - arguments: following python syntax, with 1-based indexing (instead of 0)
         *   and custom types (units)
         *   - general form: {ARG_IDX[:.NUM_DECIMAL_DIGITS][UNIT]}
         *     UNIT:
         *     - m: horizontal distance in meters
         *     - m_v: vertical distance in meters
         *     - m^2: area in m^2
         *     - m/s: speed in m/s
         *     - C: temperature in degrees celcius
         * - returned string will be trimmed (removed whitespace)
         """
        i = 0
        escape_start = 0

        def escape_previous(msg: str, up_to_n: int) -> (str, int):
            """ Escape msg[escape_start:up_to_n], and return msg[0:up_to_n]
            :param msg: string to escape
            :param up_to_n: max length
            :return: (msg, escape_length_difference)
            """
            if escape_start == up_to_n:
                return msg[0:escape_start], 0
            escaped = (msg[0:escape_start] +
                       self._event_extras['message-escape'](msg[escape_start:up_to_n]))
            return escaped, len(escaped) - up_to_n

        while i < len(msg):

            if msg[i] == '\\':  # escaped character
                msg = msg[:i] + msg[i + 1:]
                i += 1
                continue

            if msg[i] == '<':
                # extract tag with 1 optional argument
                # (assumes the argument does not contain an escaped ")
                m = re.match(r"^<([a-z]+)(?: ([a-z]+)=\"([^\"]*)\")?>(.)", msg[i:], re.DOTALL)
                if not m:
                    self._debug_print("Error: invalid or unsupported format")
                    i += 1
                    continue

                tag_name = m.group(1)
                content_start_idx = m.start(4)
                end_tag_idx = msg.find('</' + tag_name + '>', i + content_start_idx)
                if end_tag_idx == -1:
                    self._debug_print("Error: invalid format")
                    i += 1
                    continue

                tag_content = msg[i + content_start_idx:end_tag_idx]
                num_skip = 0
                if tag_name == "profile":
                    profile = ''
                    if m.group(3) is not None:
                        profile = m.group(3)
                    if profile.startswith('!'):
                        remove_content = self._profile == profile[1:]
                    else:
                        remove_content = self._profile != profile
                    if remove_content:
                        tag_content = ''
                elif tag_name == 'a':
                    if m.group(3) is None:
                        url = tag_content
                    else:
                        url = m.group(3)
                    escaped_content = self._event_extras['message-escape'](tag_content)
                    tag_content = self._event_extras['url-formatter'](escaped_content, url)
                    num_skip = len(tag_content)
                elif tag_name == 'param':
                    escaped_content = self._event_extras['message-escape'](tag_content)
                    tag_content = self._event_extras['param-formatter'](escaped_content)
                    num_skip = len(tag_content)
                else:  # unknown tag
                    self._debug_print("unknown tag: {}".format(tag_name))
                    tag_content = ''

                msg_escaped, escape_len_diff = escape_previous(msg, i)
                msg = msg_escaped + tag_content + msg[end_tag_idx + len(tag_name) + 3:]
                i += num_skip + escape_len_diff
                escape_start = i

            elif msg[i] == '{':
                arg_end_idx = msg.find('}', i)
                if arg_end_idx == -1:
                    i += 1
                    self._debug_print("Error: } not found")
                    continue
                arg = msg[i + 1:arg_end_idx]
                m = re.match(r"^(\d+)(?::(?:\.(\d+))?)?(m|m_v|m/s|m\^2|C)?$", arg)
                if not m:
                    i += 1
                    self._debug_print("Error: unknown argument format")
                    continue
                arg_idx = int(m.group(1)) - 1
                if arg_idx < 0 or arg_idx >= len(self._values):
                    i += 1
                    self._debug_print("Error: invalid argument index")
                    continue
                print_fmt = "{}"
                if m.group(2) is not None:
                    print_fmt = "{:." + m.group(2) + "f}"
                arg_value = self.argument_display_value(arg_idx)
                arg_value_str = print_fmt.format(arg_value)
                unit = m.group(3)
                if unit is not None:
                    arg_value_str += ' ' + self._parse_unit(unit)
                msg_escaped, escape_len_diff = escape_previous(msg, i)
                msg = msg_escaped + arg_value_str + msg[arg_end_idx + 1:]
                i += len(arg_value_str) + escape_len_diff
                escape_start = i
            else:
                i += 1
        msg, _ = escape_previous(msg, len(msg))
        return msg.strip()

    @staticmethod
    def _parse_unit(unit: str) -> str:
        """ Parse unit from format """
        if unit == 'm_v':
            return 'm'
        return unit


class Parser:
    """ main parsing class """

    def __init__(self, debug: bool = False):
        self._profile = "dev"
        self._events = {}
        self._enums = {}
        self._debug = debug
        self._url_formatter = lambda content, url: content
        self._param_formatter = lambda param_name: param_name
        self._message_escape = lambda msg: msg

    def load_definition_file(self, json_file: str):
        """ load event definitions from a json file """
        with open(json_file, 'r', encoding='utf-8') as j:
            self.load_definitions(json.load(j))

    def load_definitions(self, json_data: dict):
        """ load event definitions from a dict """
        # TODO: merge with self._events in case we already have definitions

        version = json_data.get('version', 0)
        if version < 1:
            raise ParserException("Unexpected version {}".format(version))
        self._events = json_data

        # convert keys from string to int
        components_int = {}
        for comp_id in self._events.get("components", []):
            components_int[int(comp_id)] = self._events["components"][comp_id]
            comp = components_int[int(comp_id)]
            for group_name in comp.get("event_groups", []):
                group = comp["event_groups"][group_name]
                if not "events" in group:
                    continue
                events_int = {}
                for event_sub_id in group["events"]:
                    events_int[int(event_sub_id)] = group["events"][event_sub_id]
                group["events"] = events_int
        self._events["components"] = components_int

        # store enums separately for faster access
        for comp_id in self._events.get("components", []):
            comp = self._events["components"][comp_id]
            namespace = comp["namespace"]
            for enum_name in comp.get("enums", []):
                enum = comp["enums"][enum_name]
                self._enums[namespace + '::' + enum_name] = enum

    def parse(self, event_id: int, arguments: bytes) -> ParsedEvent:
        """ Parse event from event ID and arguments """
        # Find ID
        events = self._events
        search_comp_id = (event_id >> 24) & 0xff
        search_event_sub_id = event_id & 0xffffff
        if search_comp_id in events.get("components", []):
            comp = events["components"][search_comp_id]
            for group_name in comp.get("event_groups", []):
                group = comp["event_groups"][group_name]
                if search_event_sub_id in group.get("events", []):
                    event = group["events"][search_event_sub_id]
                    # pass some additional info
                    event_extras = {
                        'id': event_id,
                        'namespace': comp["namespace"],
                        'group': group_name,
                        'enums': self._enums,
                        'url-formatter': self._url_formatter,
                        'param-formatter': self._param_formatter,
                        'message-escape': self._message_escape,
                    }
                    return ParsedEvent(event, event_extras, arguments, events,
                                       self._profile, self._debug)
        return None

    def set_profile(self, profile: str):
        """ set the profile name """
        self._profile = profile

    def set_url_formatter(self, formatter):
        """ set url formatter
            :param formatter: lambda with (content: str, url: str) args
        """
        self._url_formatter = formatter

    def set_param_formatter(self, formatter):
        """ set param formatter
            :param formatter: lambda with (content: str) args
        """
        self._param_formatter = formatter

    def set_message_escape_method(self, message_escape):
        """ set message escape callback method.
            Can be used to e.g. escape HTML characters in a message / description
            :param message_escape: lambda with (msg: str) args
        """
        self._message_escape = message_escape
