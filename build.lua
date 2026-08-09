module = "ulsbs"

checkengines = {"luatex"}
stdengine = "luatex"
checkformat = "latex"
checkruns = 1
testfiledir = "tests/tex"

sourcefiledir = "src/ulsbs/assets/tex"
sourcefiles = {"*.sty", "*.cls"}
installfiles = {"*.sty", "*.cls"}

-- ulsbs.sty intentionally loads its bundled songs package through this path.
-- Preserve that directory layout in l3build's otherwise flat test sandbox.
function checkinit_hook()
  local songsdir = testdir .. "/ext_packages/songs"
  mkdir(testdir .. "/ext_packages")
  mkdir(songsdir)
  cp("*", sourcefiledir .. "/ext_packages/songs", songsdir)
  return 0
end
