#include <iostream>
#include <cstdlib>
#include <cstdio>
#include <vector>
#include <ctime>


double my_rand()
{
	static bool init(false);

	if( !init )
	{
		std::srand(std::time(nullptr));
		init = true;
	}

	return double(std::rand())/RAND_MAX;
}

class TravelingSalesmanSolver
{
     private :
	std::vector<std::vector<double> > m_Costs;
	std::vector<int> m_Path;
	std::vector<bool> m_Included;
	int m_SetSize;
	double m_Cost;
	//-------------------------
	std::vector<int> m_BestPath;
	double m_BestCost;

	bool exploration_is_over( const int level )
	{
		return (level==m_Costs.size());
	}

	bool is_possible( const int choice, const int level )
	{
		return (m_Included[choice]==false);
	}

	void include( const int choice, const int level )
	{
		m_Included[choice] = true;
		m_Path.push_back(choice);
		if( level>0 )
			m_Cost += m_Costs[m_Path[level-1]][level];
	}

	void exclude( const int choice, const int level )
	{
		m_Included[choice] = false;
		m_Path.pop_back();
		if( level>0 )
			m_Cost -= m_Costs[m_Path[level-1]][level];
	}

     public :
	TravelingSalesmanSolver( const int nb_nodes )
	{
		m_BestCost = 0.0;
		m_Cost = 0.0;

		m_Costs = std::vector<std::vector<double> >(nb_nodes);

		for( std::size_t i=0; i<nb_nodes; i++ )
			m_Costs[i].resize(nb_nodes);

		std::cout << "[ matrix costs ]\n";

		for( std::size_t i=0; i<nb_nodes; i++ )
		{
			for( std::size_t j=0; j<nb_nodes; j++ )
			{
				double value(my_rand());
				m_Costs[i][j] = value;
				m_BestCost += value;
				printf("%.6f\t", value);
			}
			std::cout << '\n';
		}

		m_SetSize = nb_nodes;
		m_Included.reserve(m_SetSize);
		m_Included.assign(m_SetSize, false);
	}

	void backtracking( const int k )
	{
		if( exploration_is_over(k) )
		{
			if( m_Cost<m_BestCost )
			{
				m_BestCost = m_Cost;
				m_BestPath = m_Path;
				std::cout << "new path -> [";
				for( std::size_t k=0; k<m_Path.size(); k++ )
					std::cout << m_Path[k] << ",";
				std::cout << "] | cost=" << m_Cost << '\n';
			}
			return;
		}

		for( int i=0; i<m_SetSize; i++ )
		{
			if( is_possible(i,k) )
			{
				include(i,k);
				backtracking(k+1);
				exclude(i,k);
			}
		}
	}
};

int main( int argc, char **argv )
{
	if( argc != 2 )
	{
		std::cout << "usage: " << argv[0] << " nb_nodes\n";
		return EXIT_FAILURE;
	}

	TravelingSalesmanSolver tss(atoi(argv[1]));
	tss.backtracking(0);

	return EXIT_SUCCESS;
}
