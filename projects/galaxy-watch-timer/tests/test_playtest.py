"""Interactive Simulation & Usability Tester for TacTicTap on Wear OS.

Validates the updated gesture system:
1. Horizontal swipes for digit movement (Left: Next, Right: Prev)
2. Vertical swipes for Confirm (Up) and Reset (Down)
3. Configurable inversion for Horizontal (Left <-> Right) and Vertical (Up <-> Down)
"""

class TacTicTapSimulator:
    def __init__(self, invert_h=False, invert_v=False):
        self.state = "SETUP"
        self.digits = [0, 0, 0, 0]
        self.active_idx = 0
        self.remaining_sec = 0
        self.invert_h = invert_h
        self.invert_v = invert_v
        self.haptics = []

    def trigger_haptic(self, is_double=False):
        self.haptics.append("DOUBLE" if is_double else "CLICK")

    def tap(self, is_top=True):
        if self.state == "SETUP":
            max_val = 5 if self.active_idx == 2 else 9
            cur = self.digits[self.active_idx]
            if is_top:
                self.digits[self.active_idx] = 0 if cur >= max_val else cur + 1
            else:
                self.digits[self.active_idx] = max_val if cur <= 0 else cur - 1
            self.trigger_haptic(False)
        elif self.state == "RUNNING":
            self.state = "PAUSED"
            self.trigger_haptic(False)
        elif self.state == "PAUSED":
            self.state = "RUNNING"
            self.trigger_haptic(False)

    def swipe_horizontal(self, is_left):
        go_next = is_left if not self.invert_h else not is_left
        if self.state == "SETUP":
            if go_next:
                if self.active_idx < 3:
                    self.active_idx += 1
                    self.trigger_haptic(False)
                else:
                    # 4th digit next -> start
                    sec = (self.digits[0]*10 + self.digits[1])*60 + (self.digits[2]*10 + self.digits[3])
                    if sec > 0:
                        self.remaining_sec = sec
                        self.state = "RUNNING"
                        self.trigger_haptic(True)
            else:
                if self.active_idx > 0:
                    self.active_idx -= 1
                    self.trigger_haptic(False)

    def swipe_vertical(self, is_up):
        is_confirm = is_up if not self.invert_v else not is_up
        if is_confirm:
            if self.state == "SETUP":
                sec = (self.digits[0]*10 + self.digits[1])*60 + (self.digits[2]*10 + self.digits[3])
                if sec > 0:
                    self.remaining_sec = sec
                    self.state = "RUNNING"
                    self.trigger_haptic(True)
        else:
            # Reset
            if self.state == "SETUP":
                self.digits = [0, 0, 0, 0]
                self.active_idx = 0
                self.trigger_haptic(True)
            elif self.state == "PAUSED":
                self.state = "SETUP"
                self.active_idx = 0
                self.digits = [0, 0, 0, 0]
                self.trigger_haptic(True)


def run_tests():
    print("=== Testing Updated Gesture System ===")

    # 1. Normal mode: Left=Next, Right=Prev, Up=Confirm, Down=Reset
    sim = TacTicTapSimulator(invert_h=False, invert_v=False)
    sim.tap(True) # 10min = 1
    sim.swipe_horizontal(is_left=True) # Next digit
    assert sim.active_idx == 1
    sim.tap(True) # 1min = 1
    sim.swipe_horizontal(is_left=False) # Right swipe: Prev digit!
    assert sim.active_idx == 0
    sim.swipe_vertical(is_up=True) # Up swipe: Confirm!
    assert sim.state == "RUNNING"
    assert sim.remaining_sec == 11 * 60
    print("✔ Default Gesture Mode (Left/Right digit, Up Confirm): PASS")

    # 2. Reset test (Down swipe)
    sim2 = TacTicTapSimulator(invert_h=False, invert_v=False)
    sim2.tap(True)
    sim2.swipe_horizontal(is_left=True)
    sim2.tap(True)
    sim2.swipe_vertical(is_up=False) # Down swipe: Reset!
    assert sim2.digits == [0, 0, 0, 0]
    assert sim2.active_idx == 0
    print("✔ Reset via Down Swipe: PASS")

    # 3. Inverted mode: Right=Next, Left=Prev, Down=Confirm, Up=Reset
    sim_inv = TacTicTapSimulator(invert_h=True, invert_v=True)
    sim_inv.tap(True)
    sim_inv.swipe_horizontal(is_left=False) # Right swipe: Next digit!
    assert sim_inv.active_idx == 1
    sim_inv.swipe_vertical(is_up=False) # Down swipe: Confirm!
    assert sim_inv.state == "RUNNING"
    print("✔ Inverted Gesture Mode (Right Next, Down Confirm): PASS")

    print("\nAll Gesture & Inversion Scenarios 100% Passed!")


if __name__ == "__main__":
    run_tests()
