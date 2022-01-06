import io
import json
import sys
import time
from enum import Enum

import cv2

from lib import flask_helpers

from starlette.responses import StreamingResponse
import anki_vector
from anki_vector import util
from anki_vector import annotate

try:
    from flask import Flask, request, render_template, jsonify
except ImportError:
    sys.exit()

try:
    from PIL import Image, ImageDraw
except ImportError:
    sys.exit()


def run():
    args = util.parse_command_args()

    with anki_vector.AsyncRobot(args.serial, enable_face_detection=True, show_3d_viewer=True) as robot:
        flask_app.remote_control_vector = RemoteControlVector(robot)

    robot.camera.init_camera_feed()
    robot.behavior.drive_off_charger()

    flask_helpers.run_flask(flask_app)


def create_default_image(image_width, image_height, do_gradient=False):
    image_bytes = bytearray([0x70, 0x70, 0x70]) * image_width * image_height

    if do_gradient:
        i = 0
        for y in range(image_height):
            for x in range(image_width):
                image_bytes[i] = int(255.0 * (x / image_width))  # R
                image_bytes[i + 1] = int(255.0 * (y / image_height))  # G
                image_bytes[i + 2] = 0  # B
                i += 3

    image = Image.frombytes('RGB', (image_width, image_height), bytes(image_bytes))
    return image


flask_app = Flask(__name__)
_default_camera_image = create_default_image(320, 240)


def remap_to_range(x, x_min, x_max, out_min, out_max):
    if x < x_min:
        return out_min
    if x > x_max:
        return out_max
    ratio = (x - x_min) / (x_max - x_min)
    return out_min + ratio * (out_max - out_min)


class DebugAnnotations(Enum):
    DISABLED = 0
    ENABLED_VISION = 1
    ENABLED_ALL = 2


class RemoteControlVector:

    def __init__(self, robot):
        self.vector = robot

        self.last_lift = None
        self.last_head = None
        self.last_wheels = None

        self.drive_forwards = 0
        self.drive_back = 0
        self.turn_left = 0
        self.turn_right = 0
        self.lift_up = 0
        self.lift_down = 0
        self.head_up = 0
        self.head_down = 0

        self.go_fast = 0
        self.go_slow = 0

        self.action_queue = []

    def update_drive_state(self, key_code, is_key_down, speed_changed):
        update_driving = True
        if key_code == ord('Z'):
            self.drive_forwards = is_key_down
        elif key_code == ord('S'):
            self.drive_back = is_key_down
        elif key_code == ord('Q'):
            self.turn_left = is_key_down
        elif key_code == ord('D'):
            self.turn_right = is_key_down
        else:
            if not speed_changed:
                update_driving = False
        return update_driving

    def update_lift_state(self, key_code, is_key_down, speed_changed):
        update_lift = True
        if key_code == ord('R'):
            self.lift_up = is_key_down
        elif key_code == ord('F'):
            self.lift_down = is_key_down
        else:
            if not speed_changed:
                update_lift = False
        return update_lift

    def update_head_state(self, key_code, is_key_down, speed_changed):
        update_head = True
        if key_code == ord('T'):
            self.head_up = is_key_down
        elif key_code == ord('G'):
            self.head_down = is_key_down
        else:
            if not speed_changed:
                update_head = False
        return update_head

    def handle_key(self, key_code, is_shift_down, is_alt_down, is_key_down):

        was_go_fast = self.go_fast
        was_go_slow = self.go_slow

        self.go_fast = is_shift_down
        self.go_slow = is_alt_down

        speed_changed = (was_go_fast != self.go_fast) or (was_go_slow != self.go_slow)

        update_driving = self.update_drive_state(key_code, is_key_down, speed_changed)

        update_lift = self.update_lift_state(key_code, is_key_down, speed_changed)

        update_head = self.update_head_state(key_code, is_key_down, speed_changed)

        if update_driving:
            self.update_mouse_driving()
        if update_head:
            self.update_head()
        if update_lift:
            self.update_lift()

    def queue_action(self, new_action):
        if len(self.action_queue) > 10:
            self.action_queue.pop(0)
        self.action_queue.append(new_action)

    def update(self):
        if self.action_queue:
            queued_action, action_args = self.action_queue[0]
            if queued_action(action_args):
                self.action_queue.pop(0)

    def pick_speed(self, fast_speed, mid_speed, slow_speed):
        if self.go_fast:
            if not self.go_slow:
                return fast_speed
        elif self.go_slow:
            return slow_speed
        return mid_speed

    def update_lift(self):
        lift_speed = self.pick_speed(8, 4, 2)
        lift_vel = (self.lift_up - self.lift_down) * lift_speed
        if self.last_lift and lift_vel == self.last_lift:
            return
        self.last_lift = lift_vel
        self.vector.motors.set_lift_motor(lift_vel)

    def update_head(self):
        head_speed = self.pick_speed(2, 1, 0.5)
        head_vel = (self.head_up - self.head_down) * head_speed
        if self.last_head and head_vel == self.last_head:
            return
        self.last_head = head_vel
        self.vector.motors.set_head_motor(head_vel)

    def update_mouse_driving(self):
        drive_dir = (self.drive_forwards - self.drive_back)

        turn_dir = (self.turn_right - self.turn_left) + self.mouse_dir
        if drive_dir < 0:
            turn_dir = -turn_dir

        forward_speed = self.pick_speed(150, 75, 50)
        turn_speed = self.pick_speed(100, 50, 30)

        l_wheel_speed = (drive_dir * forward_speed) + (turn_speed * turn_dir)
        r_wheel_speed = (drive_dir * forward_speed) - (turn_speed * turn_dir)

        wheel_params = (l_wheel_speed, r_wheel_speed, l_wheel_speed * 4, r_wheel_speed * 4)
        if self.last_wheels and wheel_params == self.last_wheels:
            return
        self.last_wheels = wheel_params
        self.vector.motors.set_wheel_motors(*wheel_params)


@flask_app.route("/")
def handle_index_page():
    return render_template('index.html')


def get_annotated_image():
    image = flask_app.remote_control_vector.vector.camera.latest_image
    return image.raw_image


def streaming_video():
    while True:
        if flask_app.remote_control_vector:
            image = get_annotated_image()

            img_io = io.BytesIO()
            image.save(img_io, 'PNG')
            img_io.seek(0)
            yield (b'--frame\r\n'
                   b'Content-Type: image/png\r\n\r\n' + img_io.getvalue() + b'\r\n')
        else:
            time.sleep(.1)


@flask_app.route("/batterie")
def get_batterie():
    with anki_vector.Robot() as robot:
        battery_state = robot.get_battery_state()
        if battery_state:
            batterie = json.dumps({"volt": battery_state.battery_volts,
                                   "level": battery_state.battery_level,
                                   "on_charge": battery_state.is_charging,
                                   "on_charger": battery_state.is_on_charger_platform,
                                   "estimated_time": battery_state.suggested_charger_sec})
            return jsonify(batterie)


@flask_app.route("/view")
def handle_vectorImage():
    cv2img = streaming_video()
    res, im_png = cv2.imencode(".png", cv2img)
    return StreamingResponse(io.BytesIO(im_png.tobytes()), media_type="image/png")


def handle_key_event(key_request, is_key_down):
    message = json.loads(key_request.data.decode("utf-8"))
    if flask_app.remote_control_vector:
        flask_app.remote_control_vector.handle_key(key_code=(message['keyCode']), is_shift_down=message['hasShift'],
                                                   is_alt_down=message['hasAlt'], is_key_down=is_key_down)
    return ""


@flask_app.route('/keydown', methods=['POST'])
def handle_keydown():
    return handle_key_event(request, is_key_down=True)


@flask_app.route('/keyup', methods=['POST'])
def handle_keyup():
    return handle_key_event(request, is_key_down=False)


@flask_app.route('/updateVector', methods=['POST'])
def handle_updateVector():
    if flask_app.remote_control_vector:
        flask_app.remote_control_vector.update()

    return ""


if __name__ == '__main__':
    try:
        run()
    except KeyboardInterrupt as e:
        pass
    except anki_vector.exceptions.VectorConnectionException as e:
        sys.exit("A connection error occurred: %s" % e)
