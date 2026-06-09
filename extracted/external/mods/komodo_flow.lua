local komodo = {}

komodo.p1 = 'greptile'
komodo.p2 = 'bug'
komodo.stage = 'stages/greptile_city.def'

local originalGetSingleMenuAction = main.f_getSingleMenuAction

function main.f_getSingleMenuAction(tbl)
	if tbl ~= nil and tbl.items ~= nil then
		for _, item in ipairs(tbl.items) do
			if item.itemname == 'play' then
				return nil
			end
		end
	end
	return originalGetSingleMenuAction(tbl)
end

local function prepareMatch()
	main.f_clearShuffleTables()
	main.cpuSide = {false, true}
	main.motif.vsscreen = true
	main.motif.vsmatchno = false
	main.motif.victoryscreen = true
	main.motif.winscreen = false
	main.motif.continuescreen = false
	main.orderSelect = {false, false}
	main.selectMenu = {false, false}
	main.stageMenu = false
	main.teamMenu = {
		{single = true, simul = false, turns = false, tag = false},
		{single = true, simul = false, turns = false, tag = false},
	}
	setGameMode('komodo')
	setHomeTeam(1)
	main.f_saveBaseRemapInput()
	remapInput(1, getLastInputController())
	remapInput(getLastInputController(), 1)
	setMotifElements(main.motif)
	start.f_selectReset(true)
	main.t_availableChars = main.f_tableCopy(main.t_orderChars)
	start.reset = false
end

function komodo.launch()
	prepareMatch()
	launchFight{
		p1char = {komodo.p1},
		p2char = {komodo.p2},
		p1teammode = 'single',
		p2teammode = 'single',
		p1numchars = 1,
		p2numchars = 1,
		p1rounds = 2,
		p2rounds = 2,
		stage = komodo.stage,
		time = -1,
		vsscreen = true,
		victoryscreen = true,
		continue = false,
		p1orderselect = false,
		p2orderselect = false,
	}
	setMatchNo(-1)
	bgReset(motif[main.background].BGDef)
	fadeInInit(motif[main.group].fadein.FadeData)
	playBgm({source = 'motif.title', interrupt = true})
end

main.t_itemname.play = function(t, item)
	hook.run('main.t_itemname', t, item)
	return komodo.launch
end

return komodo
