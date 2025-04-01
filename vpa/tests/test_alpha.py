import unittest
import os
from collections import deque
import pandas as pd
from vpa.app import Candle, calculate_adx, identify_acc_or_dist
from collections import namedtuple

class TestAlphaLogic(unittest.TestCase):
    PERIOD_ONE_LENGTH = 5
    PERIOD_TWO_LENGTH = 25
    PERIOD_THREE_LENGTH = 50

    def setUp(self):
        self.deque_dictionary = {
            "period_one": deque(maxlen=TestAlphaLogic.PERIOD_ONE_LENGTH),
            "period_two": deque(maxlen=TestAlphaLogic.PERIOD_TWO_LENGTH),
            "period_three": deque(maxlen=TestAlphaLogic.PERIOD_THREE_LENGTH)
        }

        absolute_path = os.path.dirname(__file__)
        relative_path = "../data/"
        full_path = os.path.join(absolute_path, relative_path)

        self.my_data_frame = pd.read_csv(full_path + "spy_data.csv")
        self.my_data_frame = self.my_data_frame.sort_values("Date", axis=0)

    #Step 1: Read CSV file

    def test_read_csv(self):
        print(f"File Length: {len(self.my_data_frame)}")
        self.assertTrue(len(self.my_data_frame), "The DataFrame should not be empty.")
        print(f"{self.my_data_frame.columns}")

    #Step 2: Make sure the CSV file has correct data

    def test_columns_present(self):
        expected_columns = ['Date', 'Adj Close', 'Close', 'High', 'Low', 'Open', 'Volume']
        for column in expected_columns:
            self.assertIn(column, self.my_data_frame.columns, f"Missing column: {column}")

    #Step 3: Make sure we can create a Candle object from data

    def test_create_candle(self):
        first_row = self.my_data_frame.iloc[0]
        this_candle = Candle(
            first_row['Date'],
            first_row['Volume'],
            first_row['Open'],
            first_row['High'],
            first_row['Low'],
            first_row['Adj Close']
        )
        #print(this_candle)
        self.assertIsNotNone(this_candle, "Candle object should not be None.")

    def test_deque_and_adx(self):

        #Step 4: Make sure we can create a rolling window (deque) for each period length

        for index, row in self.my_data_frame.iterrows():
            if index == TestAlphaLogic.PERIOD_ONE_LENGTH + 1:
                self.assertEqual(len(self.deque_dictionary["period_one"]), TestAlphaLogic.PERIOD_ONE_LENGTH, "Deque 'period_one' + 1 test failed for period 1")
                self.assertEqual(len(self.deque_dictionary["period_two"]), TestAlphaLogic.PERIOD_ONE_LENGTH + 1, "Deque 'period_one' + 1 test failed for period 2")
                self.assertEqual(len(self.deque_dictionary["period_three"]), TestAlphaLogic.PERIOD_ONE_LENGTH + 1, "Deque 'period_one' + 1 test failed for period 3")
                with self.assertRaises(ValueError) as context:
                    calculate_adx(self.deque_dictionary["period_three"])
                self.assertEqual(str(context.exception), "Not enough data to calculate ADX. At least 15 periods are required.", "calculate_adx() should have raised a ValueError")
            elif index == TestAlphaLogic.PERIOD_TWO_LENGTH + 1:
                self.assertEqual(len(self.deque_dictionary["period_one"]), TestAlphaLogic.PERIOD_ONE_LENGTH, "Deque 'period_two' + 1 test failed for period 1")
                self.assertEqual(len(self.deque_dictionary["period_two"]), TestAlphaLogic.PERIOD_TWO_LENGTH, "Deque 'period_two' + 1 test failed for period 2")
                self.assertEqual(len(self.deque_dictionary["period_three"]), TestAlphaLogic.PERIOD_TWO_LENGTH + 1, "Deque 'period_two' + 1 test failed for period 3")
            elif index == TestAlphaLogic.PERIOD_THREE_LENGTH + 1:
                self.assertEqual(len(self.deque_dictionary["period_one"]), TestAlphaLogic.PERIOD_ONE_LENGTH, "Deque 'period_three' + 1 test failed for period 1")
                self.assertEqual(len(self.deque_dictionary["period_two"]), TestAlphaLogic.PERIOD_TWO_LENGTH, "Deque 'period_three' + 1 test failed for period 2")
                self.assertEqual(len(self.deque_dictionary["period_three"]), TestAlphaLogic.PERIOD_THREE_LENGTH, "Deque 'period_three' + 1 test failed for period 3")
            elif index == 52:
                break

            #Note we are reading only first 52 candles of the CSV here

            this_candle = Candle(
                row['Date'],
                row['Volume'],
                row['Open'],
                row['High'],
                row['Low'],
                row['Adj Close']
            )
            # This adds the candle to each of the three periods
            for key in self.deque_dictionary.keys():
                self.deque_dictionary[key].append(this_candle)

        # Note - now we have 50 candles (period three) additional processing and logic kicks in

        #Step 5: Calculate the ADX based on the last 50 candles with period of 14
        self.assertEqual(calculate_adx(self.deque_dictionary["period_three"]), [40.48136255393826, 175.39975020822467, 27.52034622638257, 19.060191841982864], "ADX calculation failed.")

    def test_bar_counting_logic(self):
        candle1 = Candle("2023-01-03 00:00:00+00:00", 3, 1., 2., 0.5, 2.)
        candle2 = Candle("2023-01-03 00:00:00+00:00", 3, 1., 2., 0.5, 2.)
        candle3 = Candle("2023-01-03 00:00:00+00:00", 3, 1., 2., 0.5, 2.)
        candle4 = Candle("2023-01-03 00:00:00+00:00", 3, 1., 2., 0.5, 2.)
        candle5 = Candle("2023-01-03 00:00:00+00:00", 3, 1., 2., 0.5, 2.)

        for candle in [candle1, candle2, candle3, candle4, candle5]:
            candle.spread_percentiles["period_one"] = 50
            candle.volume_percentiles["period_one"] = 50

        my_deque = deque([candle1, candle2, candle3, candle4, candle5], maxlen=5)

        high_spread_threshold = 55
        high_volume_threshold = 55
        anomaly_threshold = 20

        up_bar_count = sum(1 for candle in my_deque if candle.up_bar)
        high_spread_count = sum(
            1 for candle in my_deque if candle.spread_percentiles["period_one"] > high_spread_threshold)
        high_volume_count = sum(
            1 for candle in my_deque if candle.volume_percentiles["period_one"] > high_volume_threshold)
        anomaly_count = sum(1 for candle in my_deque if
                            abs(candle.spread_percentiles["period_one"] - candle.volume_percentiles["period_one"]) >
                            anomaly_threshold)

        self.assertEqual(up_bar_count, 5, "Up bar count incorrect")
        self.assertEqual(high_spread_count, 0, "High spread count incorrect")
        self.assertEqual(high_volume_count, 0, "High volume count incorrect")
        self.assertEqual(anomaly_count, 0, "Anomaly count incorrect")

        # Test with spread threshold below 50
        high_spread_threshold = 45
        high_spread_count = sum(
            1 for candle in my_deque if candle.spread_percentiles["period_one"] > high_spread_threshold)

        self.assertEqual(high_spread_count, 5, "High spread count incorrect with threshold below 50")

    def test_acc_dist_function(self):
        # Create a mock class to simulate the data structure
        self.MockData = namedtuple('MockData', ['volume', 'close'])
        # Mock data for period_three
        self.period_three = [
            self.MockData(volume=100, close=10),
            self.MockData(volume=150, close=15),
            self.MockData(volume=200, close=20),
            self.MockData(volume=250, close=25),
            self.MockData(volume=300, close=30)
        ]

        # Mock data for period_one
        self.period_one_acc = [
            self.MockData(volume=240, close=12),  # Volume > 230 (65th percentile)
            self.MockData(volume=250, close=11),  # Volume > 230 (65th percentile)
            self.MockData(volume=260, close=10),  # Volume > 230 (65th percentile)
            self.MockData(volume=270, close=9),  # Volume > 230 (65th percentile)
            self.MockData(volume=280, close=8)  # Volume > 230 (65th percentile)
        ]

        self.period_one_dist = [
            self.MockData(volume=240, close=28),  # Volume > 230 (65th percentile)
            self.MockData(volume=250, close=29),  # Volume > 230 (65th percentile)
            self.MockData(volume=260, close=30),  # Volume > 230 (65th percentile)
            self.MockData(volume=270, close=31),  # Volume > 230 (65th percentile)
            self.MockData(volume=280, close=32)  # Volume > 230 (65th percentile)
        ]

        self.period_one_neutral = [
            self.MockData(volume=60, close=18),
            self.MockData(volume=70, close=19),
            self.MockData(volume=80, close=20),
            self.MockData(volume=90, close=21),
            self.MockData(volume=100, close=22)
        ]

        result = identify_acc_or_dist(self.period_three, self.period_one_acc)
        self.assertEqual(result, (True, "Acc"), "ACC Expected")

        result = identify_acc_or_dist(self.period_three, self.period_one_dist)
        self.assertEqual(result, (True, "Dist"), "Dist Expected")

        result = identify_acc_or_dist(self.period_three, self.period_one_neutral)
        self.assertEqual(result, (False, ""), "Neutral Expected")



def suite():
    suite = unittest.TestSuite()
    suite.addTest(TestAlphaLogic('test_read_csv'))
    suite.addTest(TestAlphaLogic('test_columns_present'))
    suite.addTest(TestAlphaLogic('test_create_candle'))
    suite.addTest(TestAlphaLogic('test_deque_and_adx'))
    suite.addTest(TestAlphaLogic('test_bar_counting_logic'))
    return suite

if __name__ == '__main__':
    runner = unittest.TextTestRunner(verbosity=2)
    runner.run(suite())