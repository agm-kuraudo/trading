import mplfinance as mpf
import matplotlib.pyplot as plt

class myplot():

    def __init__(self, df):
        self.df=df

    def renko_plot(self):

        #renko_kwargs = dict(type='renko',mav=(8,20,30), volume=True,figratio=(24,12),figscale=0.75, savefig='testsave.png')
        
        apd2 = mpf.make_addplot(self.df['BollingerDown'])

        fig = mpf.figure(style='yahoo',figsize=(24,12), dpi=300)
        ax1 = fig.add_subplot()
        
        #mpf.plot(df,ax=ax1,volume=ax2)

        #mpf.plot(self.df,ax=ax1, type='ohlc',renko_params=dict(brick_size=0.25))

        apd = mpf.make_addplot(self.df[['BollingerUp', "BollingerDown"]], ax=ax1, ylabel="Bollinger Bands")

        mpf.plot(self.df,ax=ax1, type='ohlc', addplot=apd)

        fig.savefig("Testing.png")
        

        

