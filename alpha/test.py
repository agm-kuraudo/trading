import unittest
import os
from collections import deque
import pandas as pd
from alpha.candle import Candle, calculate_adx, DummyQCTrader


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
        relative_path = "data/"
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

    def test_spread_volume_percentiles(self):

        #Firstly build up our deques again for this test and calculate the ADX
        this_candle = None

        for index, row in self.my_data_frame.iterrows():
            this_candle = Candle(
                row['Date'],
                row['Volume'],
                row['Open'],
                row['High'],
                row['Low'],
                row['Adj Close']
            )
            for key in self.deque_dictionary.keys():
                self.deque_dictionary[key].append(this_candle)
            if index == 52:
                break
        adx_values = calculate_adx(self.deque_dictionary["period_three"])

        print(f"{this_candle}")

        my_trader = DummyQCTrader()
        my_trader.deque_dictionary = self.deque_dictionary

        #Step 6: Work out percentiles

        periods = [
            ("period_one", 5, 30),
            ("period_two", 25, 10),
            ("period_three", 50, 20)
        ]

        for period_key, period_length, expected_percentile in periods:
            percentile = my_trader.get_percentile_stats_legacy_version(
                prop="spread",
                period_key=period_key,
                period_length=period_length,
                this_candle=this_candle
            )
            self.assertEqual(percentile, expected_percentile,
                             f"Candle should fall in {expected_percentile}th percentile of spread values of {period_key}")
            this_candle.spread_percentiles[period_key] = percentile

        #Step 7: I think this step is missing in my application. but we need to go back to populate all of our candles in the deque

        for old_candle in self.deque_dictionary["period_one"]:
            old_candle.spread_percentiles = this_candle.spread_percentiles



def suite():
    suite = unittest.TestSuite()
    suite.addTest(TestAlphaLogic('test_read_csv'))
    suite.addTest(TestAlphaLogic('test_columns_present'))
    suite.addTest(TestAlphaLogic('test_create_candle'))
    suite.addTest(TestAlphaLogic('test_deque_and_adx'))
    suite.addTest(TestAlphaLogic('test_spread_volume_percentiles'))
    return suite

if __name__ == '__main__':
    runner = unittest.TextTestRunner(verbosity=2)
    runner.run(suite())