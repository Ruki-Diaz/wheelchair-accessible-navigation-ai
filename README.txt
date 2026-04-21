README
============================================

This project is part of Computational Intelligence.
It demonstrates a heuristic-based pathfinding approach tailored for wheelchair accessibility using environmental enhancements and terrain constraints.

====================
HOW TO RUN THE CODE:
====================

1. INSTALL PYTHON:
------------------
Make sure Python 3.x is installed on your system.
I recommend using Anaconda Distribution (https://www.anaconda.com/download) which comes with Jupyter Notebook and many libraries preinstalled.

2. INSTALL REQUIRED LIBRARIES:
------------------------------
The following Python libraries are required:

- folium
- numpy
- matplotlib
- seaborn
- networkx
- pandas
- heapq (standard library)
- math (standard library)
- tabulate
- IPython (standard with Jupyter)

Install them using pip if not already available:

    All required pip install commands are also provided in the notebook as commented lines for convenience. If they are not installed, simply uncomment them and run the code.
eg: #!pip install pandas #!pip install network (It's included in the code file)


3. RUNNING THE NOTEBOOK:
-------------------------
Step-by-step instructions:

a. Launch Anaconda Navigator or run `jupyter notebook` in your terminal.
b. Navigate to the location of the notebook and open `HD level.ipynb`.
c. Run all cells sequentially (Cell > Run All) to execute the analysis. (or press Shift + Enter key)
d. The notebook will:

   - Create an enhanced wheelchair-accessible map with 30 path segments. It  will save in the same location of the ipynb file (I will   submit the .html map incase any issues arise)
   - Implement A*
   - Visualize the path with costs
   - Implement and compare two heuristic functions
   - Enhance performance with an alternative algorithm (ed: Dijkstra)

4. OUTPUT:
----------
- The output will include visualization of shortest paths using different heuristics.
- Additional analysis and commentary will be shown in markdown cells within the notebook.

======================================
USAGE OF OPEN-SOURCE LIBRARIES:
======================================

All external libraries used are open-source and publicly available:

- Folium       : https://python-visualization.github.io/folium/
- NumPy        : https://numpy.org/
- Matplotlib   : https://matplotlib.org/
- Seaborn      : https://seaborn.pydata.org/
- NetworkX     : https://networkx.org/
- Pandas       : https://pandas.pydata.org/
- Tabulate     : https://pypi.org/project/tabulate/

To install, run:
    pip install folium numpy matplotlib seaborn networkx pandas tabulate

You may also view the map using any modern web browser by opening:
    wheelchair_accessible_map 30.html
I will include it in the submission, but you can  generate the map once you run the code.
 
